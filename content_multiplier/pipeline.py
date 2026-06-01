"""End-to-end orchestration tying Phases 1-4 together.

Two entry operations:
    run_ingest_cycle()  — Phase 1->2->3: pull new assets, transform, stage for approval.
    run_publish_cycle() — Phase 4: publish anything approved in Airtable.

Designed to be called on a schedule (cron / Make.com / the scheduler of your choice).

Dedup state is persisted to `.seen_ids.json` in the CWD (where you run `python
main.py`), so restarting the process won't reprocess files. Each entry records
the Airtable record id and content hash, which is useful for tracing and for
the future content-hash-based dedup improvement.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Set

from . import approval, distribute, ingest, transform

logger = logging.getLogger("content_multiplier")


class SeenIdStore:
    """File-backed seen-ids store with atomic writes and corruption tolerance.

    Schema on disk:
        {
          "<file_id>": {
              "processed_at": "2026-05-27T22:05:41+00:00",
              "record_id":    "recXXXXXXXXXXXXX",
              "source_file":  "sample_transcript_attribution.txt",
              "content_hash": "9cbab8b3..."
          },
          ...
        }
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._data: Dict[str, Dict[str, Any]] = self._load()

    def _load(self) -> Dict[str, Dict[str, Any]]:
        if not self.path.exists():
            return {}
        try:
            with self.path.open(encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("seen_ids file is not a JSON object")
            return data
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            logger.warning(
                "Corrupt or unreadable %s (%s); starting fresh. Old file kept as .corrupt.",
                self.path, exc,
            )
            try:
                self.path.rename(self.path.with_suffix(self.path.suffix + ".corrupt"))
            except OSError:
                pass  # best effort
            return {}

    def ids(self) -> Set[str]:
        return set(self._data.keys())

    def mark(self, file_id: str, **metadata: Any) -> None:
        self._data[file_id] = {
            "processed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **metadata,
        }
        self._save()

    def _save(self) -> None:
        """Atomic-ish: write to a temp file in the same dir, then rename."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix=".seen_ids.", suffix=".tmp", dir=str(self.path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.path)  # atomic on POSIX, near-atomic on Windows
        except Exception:
            # Best-effort cleanup if rename failed
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


_SEEN_PATH = Path.cwd() / ".seen_ids.json"
_seen_store = SeenIdStore(_SEEN_PATH)


def run_ingest_cycle() -> int:
    """Phase 1->3. Returns number of assets staged for approval."""
    staged = 0
    for clean in ingest.ingest_all(seen_ids=_seen_store.ids()):
        logger.info("Transforming %s (%d words)", clean.source.name, clean.word_count)
        drafts = transform.transform(clean)
        if drafts.errors:
            logger.warning("Transform partial failures: %s", drafts.errors)
        record_id = approval.push_drafts(clean, drafts)
        logger.info("Staged record %s for approval", record_id)
        _seen_store.mark(
            clean.source.file_id,
            record_id=record_id,
            source_file=clean.source.name,
            content_hash=clean.source.content_hash,
        )
        staged += 1
    return staged


def run_publish_cycle() -> int:
    """Phase 4. Returns number of records distributed."""
    published = 0
    for record in approval.fetch_approved():
        fields = record.get("fields", {})
        logger.info("Distributing record %s", record["id"])
        results = distribute.distribute_record(fields)
        logger.info("Distribution results: %s", results)
        approval.mark_distributed(record["id"])
        published += 1
    return published
