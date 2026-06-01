"""Phase 4 — Distribution (Hybrid draft mode).

Pushes approved Airtable drafts into Buffer as DRAFTS (not scheduled, not
published). The human-in-the-loop completes the workflow by reviewing and
hitting publish inside Buffer's UI.

Per the v1 design decisions:
  - LinkedIn — 3 separate Buffer drafts (one per LinkedIn post, headers stripped).
  - X        — ONE Buffer draft with a native thread (first post in `text`,
               continuations in `metadata.twitter.thread`).
  - Newsletter — generic webhook fallback (Buffer doesn't post newsletters).

Buffer GraphQL API — derived from https://developers.buffer.com (confidence ~88%):
  Endpoint : POST https://api.buffer.com
  Auth     : Authorization: Bearer <BUFFER_API_KEY>
  Mutation : createPost(input: { text, channelId, schedulingType, mode,
                                 saveToDraft, metadata })
  Drafts   : `saveToDraft: true` + `mode: addToQueue`. Post status becomes
             'draft' and is NOT published until the user explicitly schedules.
  Threads  : `metadata.twitter.thread = [{text, assets:[]}, ...]` — first post
             is the top-level `text`, the rest go in this array.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Protocol, Tuple

import requests

from .approval import COL_LINKEDIN, COL_NEWSLETTER, COL_XTHREAD
from .config import CONFIG

BUFFER_ENDPOINT = "https://api.buffer.com"

_CREATE_POST_MUTATION = """
mutation CreatePost($input: PostCreateInput!) {
  createPost(input: $input) {
    ... on PostActionSuccess {
      post { id text }
    }
    ... on MutationError {
      message
    }
  }
}
""".strip()

# Same marker pattern as transform._parse_x_posts — keep in sync.
_POST_MARKER = re.compile(r"(?:^|\n)\s*(\d+)/\s*", re.MULTILINE)

# LinkedIn output structure (from prompts/linkedin.md):
#   **Post 1 — Narrative**
#   <body>
#   ---
#   **Post 2 — Single Tactic**
#   <body>
#   ---
#   **Post 3 — Framework / Principle**
#   <body>
_LI_HEADER = re.compile(r"^\s*\*\*\s*Post\s+\d+[^*]*\*\*\s*\n*", re.IGNORECASE)
_LI_SEPARATOR = re.compile(r"\n+\s*---\s*\n+")


# --------------------------------------------------------------------------- #
# Parsers — turn raw module output into ready-to-publish content
# --------------------------------------------------------------------------- #
def _strip_linkedin_headers(text: str) -> List[str]:
    """Split LinkedIn output into 3 clean posts; remove `**Post N — Label**` headers."""
    if not text.strip():
        return []
    chunks = _LI_SEPARATOR.split(text.strip())
    cleaned = []
    for chunk in chunks:
        body = _LI_HEADER.sub("", chunk, count=1).strip()
        if body:
            cleaned.append(body)
    return cleaned


def _split_x_thread(text: str) -> Tuple[Optional[str], List[str]]:
    """Parse the X module output into (first_post, [continuations]).

    Each returned string includes its `N/` prefix so it publishes as written.
    """
    matches = list(_POST_MARKER.finditer(text))
    if not matches:
        return None, []
    posts: List[str] = []
    for i, m in enumerate(matches):
        n = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        posts.append(f"{n}/ {body}" if body else f"{n}/")
    return posts[0], posts[1:]


# --------------------------------------------------------------------------- #
# Distribution targets
# --------------------------------------------------------------------------- #
class DistributionTarget(Protocol):
    def publish(self, text: str, channel_id: str, **kwargs: Any) -> dict: ...


class BufferTarget:
    """Posts to Buffer via the GraphQL createPost mutation.

    Default is DRAFT mode (saveToDraft=True, mode=addToQueue) per Phase 4 design.
    Supports X threads via the `thread_continuations` kwarg.
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._key = api_key or CONFIG.buffer_key()

    def publish(
        self,
        text: str,
        channel_id: str,
        *,
        save_to_draft: bool = True,
        thread_continuations: Optional[List[str]] = None,
        twitter: bool = False,
    ) -> dict:
        post_input: Dict[str, Any] = {
            "text": text,
            "channelId": channel_id,
            "schedulingType": "automatic",
            "mode": "addToQueue",
        }
        if save_to_draft:
            post_input["saveToDraft"] = True

        if thread_continuations:
            if not twitter:
                raise ValueError(
                    "thread_continuations is only supported when twitter=True."
                )
            post_input["metadata"] = {
                "twitter": {
                    "thread": [{"text": t, "assets": []} for t in thread_continuations]
                }
            }

        resp = requests.post(
            BUFFER_ENDPOINT,
            headers={
                "Authorization": f"Bearer {self._key}",
                "Content-Type": "application/json",
            },
            json={
                "query": _CREATE_POST_MUTATION,
                "variables": {"input": post_input},
            },
            timeout=30,
        )
        resp.raise_for_status()
        payload = resp.json()

        if payload.get("errors"):
            raise RuntimeError(f"Buffer GraphQL error: {payload['errors']}")
        result = payload["data"]["createPost"]
        if "message" in result and "post" not in result:
            raise RuntimeError(f"Buffer rejected post: {result['message']}")
        return result["post"]


class WebhookTarget:
    """Generic JSON webhook (used for newsletter — Buffer doesn't handle that channel)."""

    def __init__(self, url: Optional[str] = None) -> None:
        self._url = url or CONFIG.distribution_webhook_url

    def publish(self, text: str, channel_id: str, **kwargs: Any) -> dict:
        if not self._url:
            raise RuntimeError("DISTRIBUTION_WEBHOOK_URL not set.")
        resp = requests.post(
            self._url,
            json={"text": text, "channel": channel_id},
            timeout=30,
        )
        resp.raise_for_status()
        return {"status": "sent", "http_status": resp.status_code}


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def distribute_record(record_fields: dict, **_unused: Any) -> dict:
    """Route the three drafts to their configured destinations as Buffer drafts.

    Returns a dict mapping `{column_name -> list_of_per_post_results}` so the
    caller can see which post(s) succeeded or failed without blowing the whole
    operation up on one bad call. Errors are captured, never raised out.
    """
    results: Dict[str, List[Any]] = {
        COL_LINKEDIN: [],
        COL_XTHREAD: [],
        COL_NEWSLETTER: [],
    }

    # LinkedIn — three separate drafts
    li_channel = CONFIG.buffer_channel_id_linkedin
    li_text = (record_fields.get(COL_LINKEDIN) or "").strip()
    if li_text and li_channel:
        posts = _strip_linkedin_headers(li_text)
        for i, post in enumerate(posts, 1):
            try:
                res = BufferTarget().publish(post, li_channel, save_to_draft=True)
                results[COL_LINKEDIN].append({"index": i, "post_id": res.get("id")})
            except Exception as exc:
                results[COL_LINKEDIN].append({"index": i, "error": repr(exc)})
    elif li_text and not li_channel:
        results[COL_LINKEDIN].append({"error": "BUFFER_CHANNEL_ID_LINKEDIN not set"})

    # X — single draft with native thread continuations
    x_channel = CONFIG.buffer_channel_id_x
    x_text = (record_fields.get(COL_XTHREAD) or "").strip()
    if x_text and x_channel:
        first, rest = _split_x_thread(x_text)
        if first is None:
            results[COL_XTHREAD].append({"error": "could not parse X thread"})
        else:
            try:
                res = BufferTarget().publish(
                    first,
                    x_channel,
                    save_to_draft=True,
                    thread_continuations=rest,
                    twitter=True,
                )
                results[COL_XTHREAD].append(
                    {"post_id": res.get("id"), "thread_size": 1 + len(rest)}
                )
            except Exception as exc:
                results[COL_XTHREAD].append({"error": repr(exc)})
    elif x_text and not x_channel:
        results[COL_XTHREAD].append({"error": "BUFFER_CHANNEL_ID_X not set"})

    # Newsletter — webhook fallback
    nl_text = (record_fields.get(COL_NEWSLETTER) or "").strip()
    if nl_text:
        try:
            res = WebhookTarget().publish(nl_text, "newsletter")
            results[COL_NEWSLETTER].append(res)
        except Exception as exc:
            results[COL_NEWSLETTER].append({"error": repr(exc)})

    return results


# --------------------------------------------------------------------------- #
# Helper: discover the user's Buffer channel IDs (used by `python main.py channels`)
# --------------------------------------------------------------------------- #
_CHANNELS_QUERY = """
query MyChannels {
  channels {
    id
    name
    service
  }
}
""".strip()


def list_channels() -> List[Dict[str, str]]:
    """Return all Buffer channels available to the configured API key."""
    resp = requests.post(
        BUFFER_ENDPOINT,
        headers={
            "Authorization": f"Bearer {CONFIG.buffer_key()}",
            "Content-Type": "application/json",
        },
        json={"query": _CHANNELS_QUERY},
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("errors"):
        raise RuntimeError(f"Buffer GraphQL error: {payload['errors']}")
    return payload["data"]["channels"]
