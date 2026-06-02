"""Cost monitoring + alerting, sourced from the Airtable history.

Counts generations across time windows (today / last 7 days / current calendar
month / all time), multiplies by the configured per-generation cost estimate,
and optionally fires a one-shot monthly webhook when spend crosses a threshold.

This is *estimated* spend, not actual token-counted spend. Good enough for
"am I about to blow past my budget" monitoring. For exact accounting,
Anthropic's console is the source of truth.

Design choices:
- Time windowing is computed in Python (UTC) rather than via Airtable
  formulas — predictable, no timezone gotchas.
- The "alerted this month" flag is in-memory; on container restart we may
  re-alert once for the same month. Acceptable trade-off vs adding a
  persistence layer just for one boolean.
- Both functions are safe to call without Airtable configured; they return
  an `available: false` summary instead of raising.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import requests

from .config import CONFIG
from .web_history import TABLE_NAME

logger = logging.getLogger("content_multiplier.cost_monitor")

# Read once at import; same pattern as other env-driven settings.
MONTHLY_ALERT_USD = float(os.getenv("MONTHLY_ALERT_USD", "0"))
MONTHLY_ALERT_WEBHOOK_URL = os.getenv("MONTHLY_ALERT_WEBHOOK_URL", "")

# In-process memo: which "YYYY-MM" we've already alerted for, so a single
# threshold cross doesn't spam the webhook on every /stats refresh.
_last_alerted_month: Optional[str] = None


def _empty_summary(cost_per_gen: float, threshold: float) -> Dict[str, Any]:
    base = {"count": 0, "estimated_cost_usd": 0.0}
    return {
        "available": False,
        "cost_per_gen_usd": cost_per_gen,
        "alert_threshold_usd": threshold,
        "monthly_alert_active": False,
        "today": dict(base),
        "last_7_days": dict(base),
        "this_month": dict(base),
        "all_time": dict(base),
    }


def _table():
    from pyairtable import Api

    api = Api(CONFIG.airtable_key())
    return api.table(CONFIG.airtable_base_id, TABLE_NAME)


def _parse_submitted_at(record: dict) -> Optional[datetime]:
    val = record.get("fields", {}).get("Submitted At")
    if not val:
        return None
    try:
        return datetime.fromisoformat(str(val).replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def get_usage_summary() -> Dict[str, Any]:
    """Aggregate counts + estimated costs across today / 7d / month / all-time."""
    cost_per_gen = float(os.getenv("COST_PER_GENERATION_USD", "0.08"))
    threshold = MONTHLY_ALERT_USD

    if not CONFIG.airtable_base_id:
        return _empty_summary(cost_per_gen, threshold)

    try:
        records = _table().all(fields=["Submitted At"])
    except Exception:
        logger.exception("Airtable query failed in get_usage_summary; returning empty")
        return _empty_summary(cost_per_gen, threshold)

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now - timedelta(days=7)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    counts = {"today": 0, "last_7_days": 0, "this_month": 0, "all_time": len(records)}
    for r in records:
        ts = _parse_submitted_at(r)
        if ts is None:
            continue
        if ts >= today_start:
            counts["today"] += 1
        if ts >= week_start:
            counts["last_7_days"] += 1
        if ts >= month_start:
            counts["this_month"] += 1

    out: Dict[str, Any] = {
        "available": True,
        "cost_per_gen_usd": cost_per_gen,
        "alert_threshold_usd": threshold,
    }
    for k, n in counts.items():
        out[k] = {"count": n, "estimated_cost_usd": round(n * cost_per_gen, 4)}

    monthly_cost = out["this_month"]["estimated_cost_usd"]
    out["monthly_alert_active"] = bool(threshold > 0 and monthly_cost >= threshold)
    return out


def check_and_alert(summary: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """If monthly threshold crossed AND we haven't alerted this month, fire webhook.

    Returns a dict describing the fire attempt (status_code or error), or None
    if no alert was attempted (not over threshold, no webhook URL, already
    alerted this month, or Airtable unavailable).
    """
    global _last_alerted_month

    if not MONTHLY_ALERT_WEBHOOK_URL:
        return None
    if not summary.get("monthly_alert_active"):
        return None

    this_month = datetime.now(timezone.utc).strftime("%Y-%m")
    if _last_alerted_month == this_month:
        return {"status": "already_alerted_this_month"}

    payload = {
        "alert": "monthly_cost_threshold_exceeded",
        "month_utc": this_month,
        "threshold_usd": summary["alert_threshold_usd"],
        "estimated_cost_usd": summary["this_month"]["estimated_cost_usd"],
        "generations_this_month": summary["this_month"]["count"],
    }
    try:
        resp = requests.post(MONTHLY_ALERT_WEBHOOK_URL, json=payload, timeout=10)
        _last_alerted_month = this_month  # mark even on non-2xx so we don't spam
        logger.warning(
            "Monthly cost alert fired: $%s/$%s, webhook -> %s",
            payload["estimated_cost_usd"], payload["threshold_usd"], resp.status_code,
        )
        return {"status": "fired", "http_status": resp.status_code, "ok": resp.ok}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Alert webhook failed")
        return {"status": "error", "detail": repr(exc)}


def reset_alert_memo_for_tests() -> None:
    """Test-only helper: clear the in-memory 'already alerted' marker."""
    global _last_alerted_month
    _last_alerted_month = None
