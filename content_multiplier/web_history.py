"""Persist each successful /generate submission to Airtable.

Writes to the "Web Generations" table in the same base the dormant CLI
approval workflow used. Schema is set up via the Airtable connector; see
the table description in Airtable for field-level docs.

If AIRTABLE_API_KEY or AIRTABLE_BASE_ID are unset, save() is a no-op so the
web app keeps working in local dev without Airtable. The caller is also
expected to wrap calls in try/except so a history failure can never break a
/generate response.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .config import CONFIG

logger = logging.getLogger("content_multiplier.web_history")

TABLE_NAME = os.getenv("WEB_HISTORY_TABLE", "Web Generations")

# singleLineText fields have a 255-char limit in Airtable. Keep summaries safe.
_PRIMARY_MAX = 255


def _table():
    from pyairtable import Api

    api = Api(CONFIG.airtable_key())
    return api.table(CONFIG.airtable_base_id, TABLE_NAME)


def _short_topic(topic: str, limit: int = 60) -> str:
    """Collapse whitespace and truncate for the primary 'Generation' field."""
    one_line = " ".join(topic.split())
    if len(one_line) <= limit:
        return one_line
    return one_line[: limit - 1].rstrip() + "…"


def _format_errors(errors: Optional[Dict[str, Any]]) -> str:
    if not errors:
        return ""
    return "\n".join(f"{k}: {v}" for k, v in errors.items())


def save(
    *,
    topic: str,
    tone: str,
    audience: str,
    length: str,
    format: str,
    transcript: str,
    word_count: int,
    linkedin: str,
    x_thread: str,
    newsletter: str,
    errors: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Save one generation. Returns the record id on success, None on skip/failure.

    Designed to be safe to call without checking config: missing Airtable
    credentials make this a no-op rather than an exception.
    """
    if not CONFIG.airtable_base_id:
        logger.debug("AIRTABLE_BASE_ID unset; skipping history save")
        return None
    try:
        now = datetime.now(timezone.utc)
        summary = f"{now.strftime('%Y-%m-%d %H:%M')} — {_short_topic(topic)}"
        fields = {
            "Generation": summary[:_PRIMARY_MAX],
            "Submitted At": now.isoformat(timespec="seconds"),
            "Topic": topic,
            "Format": format.capitalize(),  # 'monologue' -> 'Monologue'
            "Tone": tone,
            "Audience": audience,
            "Length": length,
            "Word Count": int(word_count or 0),
            "Transcript": transcript,
            "LinkedIn Drafts": linkedin,
            "X Thread": x_thread,
            "Newsletter": newsletter,
            "Errors": _format_errors(errors),
        }
        record = _table().create(fields)
        logger.info("History saved: %s", record.get("id"))
        return record.get("id")
    except Exception:
        logger.exception("Failed to save generation to Airtable history")
        return None
