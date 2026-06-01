"""Web pipeline: transcript generation -> 3 transform modules -> JSON-ready dict.

Replaces the file-based pipeline.py orchestration for the Flask app. No Airtable,
no dedup state, no Buffer — just generate and return.
"""

from __future__ import annotations

from typing import Any, Dict

from . import generate_transcript, transform


def generate_all(*, topic: str, tone: str, audience: str, length: str) -> Dict[str, Any]:
    """Run the full web pipeline for one user submission.

    Returns a dict shaped for the Flask response — already JSON-serializable.
    """
    clean = generate_transcript.generate(
        topic=topic, tone=tone, audience=audience, length=length
    )
    drafts = transform.transform(clean)
    return {
        "transcript": clean.text,
        "word_count": clean.word_count,
        "source_name": clean.source.name,
        "linkedin": drafts.linkedin,
        "x_thread": drafts.x_thread,
        "newsletter": drafts.newsletter,
        "errors": drafts.errors,
    }
