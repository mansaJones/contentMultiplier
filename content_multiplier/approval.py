"""Phase 3 — Content Gateway Control Center (Airtable).

Pushes generated drafts into an Airtable table with these columns:
    Original Transcript | LinkedIn Draft | X Thread Draft | Newsletter Copy | Status

New rows default to Status = "Pending Creative Approval". Phase 4 polls for rows
flipped to "Approved for Distribution".

pyairtable — confidence ~85%.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .config import CONFIG
from .models import CleanText, TransformOutput

STATUS_PENDING = "Pending Creative Approval"
STATUS_APPROVED = "Approved for Distribution"
STATUS_DISTRIBUTED = "Distributed"

# Column names — keep in sync with your Airtable base.
COL_TRANSCRIPT = "Original Transcript"
COL_LINKEDIN = "LinkedIn Draft"
COL_XTHREAD = "X Thread Draft"
COL_NEWSLETTER = "Newsletter Copy"
COL_STATUS = "Status"
COL_SOURCE = "Source File"


def _table():
    from pyairtable import Api

    api = Api(CONFIG.airtable_key())
    return api.table(CONFIG.airtable_base_id, CONFIG.airtable_table_name)


def push_drafts(clean: CleanText, drafts: TransformOutput) -> str:
    """Create one Airtable record for an asset's drafts. Returns the record id."""
    fields: Dict[str, Any] = {
        COL_SOURCE: clean.source.name,
        COL_TRANSCRIPT: clean.text,
        COL_LINKEDIN: drafts.linkedin,
        COL_XTHREAD: drafts.x_thread,
        COL_NEWSLETTER: drafts.newsletter,
        COL_STATUS: STATUS_PENDING,
    }
    record = _table().create(fields)
    return record["id"]


def fetch_approved() -> List[Dict[str, Any]]:
    """Return records whose Status == Approved for Distribution.

    Uses a filterByFormula so we don't drag the whole table over the wire.
    """
    formula = f"{{{COL_STATUS}}} = '{STATUS_APPROVED}'"
    return _table().all(formula=formula)


def mark_distributed(record_id: str) -> None:
    """Flip a record to Distributed so it isn't picked up again."""
    _table().update(record_id, {COL_STATUS: STATUS_DISTRIBUTED})
