"""Persist email captures from the web app's unlock gate to Airtable.

Writes to the "Leads" table in the same base as Web Generations. One row
per unlock submission (no dedup — re-submissions after cookie expiry are a
real engagement signal worth keeping).

If Airtable isn't configured, save() is a no-op and the gate still works
(the cookie still gets set) — but the lead just isn't persisted. Loud
warning in the logs so you know to fix it.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

from .config import CONFIG

logger = logging.getLogger("content_multiplier.leads")

LEADS_TABLE_NAME = os.getenv("LEADS_TABLE", "Leads")
_PRIMARY_MAX = 255

# Pragmatic email regex — catches typos, lets through edge cases on purpose.
# Stricter validation belongs in a real signup flow, not a soft email gate.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(value: str) -> bool:
    if not value or len(value) > 254:
        return False
    return bool(_EMAIL_RE.match(value.strip()))


def _table():
    from pyairtable import Api

    api = Api(CONFIG.airtable_key())
    return api.table(CONFIG.airtable_base_id, LEADS_TABLE_NAME)


def save(
    *,
    email: str,
    ip_address: str = "",
    user_agent: str = "",
) -> Optional[str]:
    """Record a lead. Returns the Airtable record id on success, else None.

    Never raises — the unlock gate must succeed for the visitor even if the
    Airtable write fails. We just log the failure.
    """
    if not CONFIG.airtable_base_id:
        logger.warning("AIRTABLE_BASE_ID unset; lead NOT persisted: %s", email)
        return None
    try:
        now = datetime.now(timezone.utc)
        summary = f"{now.strftime('%Y-%m-%d %H:%M')} — {email}"
        fields = {
            "Lead": summary[:_PRIMARY_MAX],
            "Submitted At": now.isoformat(timespec="seconds"),
            "Email": email,
            "IP Address": ip_address or "",
            "User Agent": (user_agent or "")[:1000],  # cap noisy UAs
            "Status": "New",
        }
        record = _table().create(fields)
        rid = record.get("id")
        logger.info("Lead captured: %s -> %s", email, rid)
        return rid
    except Exception:
        logger.exception("Failed to save lead to Airtable")
        return None
