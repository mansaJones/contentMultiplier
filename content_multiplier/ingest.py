"""Phase 1 — Ingestion & Extraction.

Two ingestion backends, selected by config:
  - LOCAL FOLDER  (CONFIG.ingest_source_dir set)  — preferred for desktop use;
    zero Google auth, just reads files from a directory on disk. If that
    directory lives inside a Drive File Stream mount you still get cloud sync
    for free.
  - DRIVE API    (otherwise) — server-side polling via a Google service
    account (GOOGLE_CREDENTIALS_JSON), source folder shared with the SA email.

In both modes:
  - audio/video  -> Whisper -> transcript
  - text/markdown -> scrub -> clean string
"""

from __future__ import annotations

import hashlib
import io
import mimetypes
import re
from pathlib import Path
from typing import Iterator, List, Set

from .config import CONFIG
from .models import AssetKind, CleanText, SourceAsset

_AUDIO_VIDEO_HINTS = ("audio/", "video/")
_DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


# --------------------------------------------------------------------------- #
# Drive client
# --------------------------------------------------------------------------- #
def _drive_service():
    """Build a Drive v3 client from the configured service-account JSON."""
    from google.oauth2 import service_account  # lazy import
    from googleapiclient.discovery import build

    if not CONFIG.google_credentials_json:
        raise RuntimeError("GOOGLE_CREDENTIALS_JSON not set.")
    creds = service_account.Credentials.from_service_account_file(
        CONFIG.google_credentials_json, scopes=_DRIVE_SCOPES
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _classify(mime_type: str) -> AssetKind:
    if any(mime_type.startswith(h) for h in _AUDIO_VIDEO_HINTS):
        return AssetKind.AUDIO_VIDEO
    return AssetKind.TEXT


def _guess_mime(path: Path) -> str:
    mt, _ = mimetypes.guess_type(path.name)
    return mt or "text/plain"


def _list_local_assets(seen_ids: Set[str] | None = None) -> List[SourceAsset]:
    """List ingestable files in CONFIG.ingest_source_dir (local-folder mode)."""
    seen_ids = seen_ids or set()
    root = Path(CONFIG.ingest_source_dir)
    if not root.exists():
        raise RuntimeError(f"INGEST_SOURCE_DIR not found: {root}")
    if not root.is_dir():
        raise RuntimeError(f"INGEST_SOURCE_DIR is not a directory: {root}")
    assets: List[SourceAsset] = []
    for path in sorted(root.iterdir()):
        if not path.is_file() or path.name.startswith("."):
            continue
        file_id = f"local:{path.name}"
        if file_id in seen_ids:
            continue
        mime = _guess_mime(path)
        assets.append(
            SourceAsset(
                file_id=file_id,
                name=path.name,
                mime_type=mime,
                kind=_classify(mime),
                local_path=str(path),
            )
        )
    return assets


def list_new_assets(seen_ids: Set[str] | None = None) -> List[SourceAsset]:
    """Local folder mode takes precedence; falls back to Drive API."""
    if CONFIG.ingest_source_dir:
        return _list_local_assets(seen_ids)
    return _list_drive_assets(seen_ids)


def _list_drive_assets(seen_ids: Set[str] | None = None) -> List[SourceAsset]:
    """Drive API path — poll the source folder for new files.

    Simple poll-based watcher. For production, swap to Drive `changes.watch`
    push notifications (Future Improvement: dedup via content_hash).
    """
    seen_ids = seen_ids or set()
    if not CONFIG.drive_source_folder_id:
        raise RuntimeError("DRIVE_SOURCE_FOLDER_ID not set.")

    service = _drive_service()
    query = f"'{CONFIG.drive_source_folder_id}' in parents and trashed = false"
    assets: List[SourceAsset] = []
    page_token = None
    while True:
        resp = (
            service.files()
            .list(
                q=query,
                fields="nextPageToken, files(id, name, mimeType)",
                pageToken=page_token,
            )
            .execute()
        )
        for f in resp.get("files", []):
            if f["id"] in seen_ids:
                continue
            assets.append(
                SourceAsset(
                    file_id=f["id"],
                    name=f["name"],
                    mime_type=f["mimeType"],
                    kind=_classify(f["mimeType"]),
                )
            )
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return assets


def download_asset(asset: SourceAsset) -> SourceAsset:
    """Download a Drive file to DOWNLOAD_DIR and stamp local_path + content_hash."""
    from googleapiclient.http import MediaIoBaseDownload

    CONFIG.ensure_dirs()
    service = _drive_service()
    dest = CONFIG.download_dir / asset.name

    request = service.files().get_media(fileId=asset.file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()

    data = buf.getvalue()
    dest.write_bytes(data)
    asset.local_path = str(dest)
    asset.content_hash = hashlib.sha256(data).hexdigest()
    return asset


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #
def _transcribe_whisper(path: str) -> str:
    """OpenAI Whisper transcription (confidence ~90%)."""
    from openai import OpenAI

    client = OpenAI(api_key=CONFIG.openai_key())
    with open(path, "rb") as fh:
        result = client.audio.transcriptions.create(
            model=CONFIG.whisper_model,
            file=fh,
            response_format="text",
        )
    # response_format="text" returns a plain string
    return result if isinstance(result, str) else getattr(result, "text", str(result))


_MD_PATTERNS = [
    (re.compile(r"`{1,3}[^`]*`{1,3}"), ""),     # inline/code fences
    (re.compile(r"!\[[^\]]*\]\([^)]*\)"), ""),    # images
    (re.compile(r"\[([^\]]+)\]\([^)]*\)"), r"\1"),  # links -> label
    (re.compile(r"^#{1,6}\s*", re.M), ""),          # headings
    (re.compile(r"[*_>#-]{1,}"), " "),               # residual md tokens
    (re.compile(r"\n{3,}"), "\n\n"),                  # collapse blank runs
]


def _scrub_markdown(raw: str) -> str:
    text = raw
    for pat, repl in _MD_PATTERNS:
        text = pat.sub(repl, text)
    return text.strip()


def extract(asset: SourceAsset) -> CleanText:
    """Turn a downloaded asset into normalized CleanText."""
    if not asset.local_path:
        asset = download_asset(asset)

    if asset.kind is AssetKind.AUDIO_VIDEO:
        text = _transcribe_whisper(asset.local_path)
    else:
        raw = Path(asset.local_path).read_text(encoding="utf-8", errors="replace")
        text = _scrub_markdown(raw)

    return CleanText(source=asset, text=text)


def ingest_all(seen_ids: Set[str] | None = None) -> Iterator[CleanText]:
    """Convenience generator: list -> download -> extract for each new asset."""
    for asset in list_new_assets(seen_ids):
        yield extract(asset)
