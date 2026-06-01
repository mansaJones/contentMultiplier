"""Synthetic transcript generator.

For the web app: takes a user-provided topic + options, asks Claude to produce
a podcast-style transcript with the messy spoken cadence that the downstream
transform modules expect.

Returns a CleanText so it slots directly into transform.transform().
"""

from __future__ import annotations

from pathlib import Path

from .config import CONFIG
from .models import AssetKind, CleanText, SourceAsset

_PROMPT_PATH = Path(__file__).parent / "prompts" / "transcript_generator.md"

# Transcripts cap at ~900 words. ~1.5 tokens per word + headroom.
_MAX_TOKENS = 2500


def _call_claude(prompt: str) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=CONFIG.anthropic_key())
    resp = client.messages.create(
        model=CONFIG.anthropic_model,
        max_tokens=_MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(
        block.text for block in resp.content if getattr(block, "type", None) == "text"
    ).strip()


def generate(*, topic: str, tone: str, audience: str, length: str) -> CleanText:
    """Generate a synthetic transcript and wrap it as a CleanText asset."""
    template = _PROMPT_PATH.read_text(encoding="utf-8")
    prompt = template.format(topic=topic, tone=tone, audience=audience, length=length)
    text = _call_claude(prompt)
    asset = SourceAsset(
        file_id=f"generated:{topic[:40]}",
        name=f"generated_{topic[:40].replace(' ', '_')}.txt",
        mime_type="text/plain",
        kind=AssetKind.TEXT,
    )
    return CleanText(source=asset, text=text)
