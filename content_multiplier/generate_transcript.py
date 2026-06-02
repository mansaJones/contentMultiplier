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

_PROMPT_DIR = Path(__file__).parent / "prompts"

# Format -> prompt filename. Add new formats here (e.g. co_hosts, panel).
_FORMAT_PROMPTS = {
    "monologue": "transcript_generator.md",  # solo host monologue (default)
    "interview": "transcript_interview.md",  # host + guest
}
_DEFAULT_FORMAT = "monologue"

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


def generate(
    *,
    topic: str,
    tone: str,
    audience: str,
    length: str,
    format: str = _DEFAULT_FORMAT,
) -> CleanText:
    """Generate a synthetic transcript and wrap it as a CleanText asset.

    `format` selects the prompt template: 'monologue' (solo host) or
    'interview' (host + guest). Unknown formats fall back to monologue.
    """
    fmt = (format or _DEFAULT_FORMAT).lower()
    prompt_file = _FORMAT_PROMPTS.get(fmt, _FORMAT_PROMPTS[_DEFAULT_FORMAT])
    template = (_PROMPT_DIR / prompt_file).read_text(encoding="utf-8")
    prompt = template.format(topic=topic, tone=tone, audience=audience, length=length)
    text = _call_claude(prompt)
    asset = SourceAsset(
        file_id=f"generated:{fmt}:{topic[:40]}",
        name=f"generated_{fmt}_{topic[:40].replace(' ', '_')}.txt",
        mime_type="text/plain",
        kind=AssetKind.TEXT,
    )
    return CleanText(source=asset, text=text)
