"""Central config. Reads from environment (.env). Fails loud on missing critical keys
only when a phase actually needs them — not at import time — so the skeleton can be
imported and inspected without a fully populated .env.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise RuntimeError(
            f"Missing required env var '{key}'. Copy .env.example to .env and fill it in."
        )
    return val


@dataclass(frozen=True)
class Config:
    # Phase 2 — Anthropic
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

    # Phase 1 — Whisper
    whisper_model: str = os.getenv("WHISPER_MODEL", "whisper-1")

    # Phase 1 — Drive (server-side API mode)
    google_credentials_json: str = os.getenv("GOOGLE_CREDENTIALS_JSON", "")
    drive_source_folder_id: str = os.getenv("DRIVE_SOURCE_FOLDER_ID", "")

    # Phase 1 — Local folder mode (preferred when set; bypasses Google API entirely)
    ingest_source_dir: str = os.getenv("INGEST_SOURCE_DIR", "")

    # Phase 3 — Airtable
    airtable_base_id: str = os.getenv("AIRTABLE_BASE_ID", "")
    airtable_table_name: str = os.getenv("AIRTABLE_TABLE_NAME", "Content Multiplier")

    # Phase 4 — Distribution (Buffer GraphQL)
    buffer_channel_id_linkedin: str = os.getenv("BUFFER_CHANNEL_ID_LINKEDIN", "")
    buffer_channel_id_x: str = os.getenv("BUFFER_CHANNEL_ID_X", "")
    buffer_channel_id_newsletter: str = os.getenv("BUFFER_CHANNEL_ID_NEWSLETTER", "")
    distribution_webhook_url: str = os.getenv("DISTRIBUTION_WEBHOOK_URL", "")

    # Local dirs
    download_dir: Path = field(
        default_factory=lambda: Path(os.getenv("DOWNLOAD_DIR", "./_work/downloads"))
    )
    transcript_dir: Path = field(
        default_factory=lambda: Path(os.getenv("TRANSCRIPT_DIR", "./_work/transcripts"))
    )

    # Secrets — fetched lazily so import never explodes
    def anthropic_key(self) -> str:
        return _require("ANTHROPIC_API_KEY")

    def openai_key(self) -> str:
        return _require("OPENAI_API_KEY")

    def airtable_key(self) -> str:
        return _require("AIRTABLE_API_KEY")

    def buffer_key(self) -> str:
        return _require("BUFFER_API_KEY")

    def ensure_dirs(self) -> None:
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.transcript_dir.mkdir(parents=True, exist_ok=True)


CONFIG = Config()
