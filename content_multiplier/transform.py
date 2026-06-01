"""Phase 2 — Channel-specific transform modules.

Runs three Claude prompts concurrently against one CleanText and returns a
TransformOutput. Prompts live in prompts/*.md and are fed the shared
style_guardrails.md so brand voice stays consistent (Phase 5).

Anthropic Messages API — confidence ~95%.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Dict, List, Tuple

from .config import CONFIG
from .models import CleanText, TransformOutput

_PROMPT_DIR = Path(__file__).parent / "prompts"
_MODULES = ("linkedin", "x_thread", "newsletter")

# Generous ceiling; threads/posts are short but we leave headroom.
_MAX_TOKENS = 2000

# X thread enforcement — hard 280-char limit, with bounded re-prompt retries.
X_HARD_LIMIT = 280
_X_REPAIR_MAX_RETRIES = 2
# Marker-based parser so we catch the body whether Claude puts it on the same
# line as `N/` or on the following line. (The original single-line regex
# silently missed multi-line posts and let an over-limit post slip through.)
_POST_MARKER = re.compile(r"(?:^|\n)\s*(\d+)/\s*", re.MULTILINE)


def _load_prompt(module: str, transcript: str, guardrails: str) -> str:
    template = (_PROMPT_DIR / f"{module}.md").read_text(encoding="utf-8")
    return template.format(transcript=transcript, guardrails=guardrails)


def _guardrails() -> str:
    return (_PROMPT_DIR / "style_guardrails.md").read_text(encoding="utf-8")


def _call_claude(prompt: str) -> str:
    """Single Messages API call returning concatenated text blocks."""
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


def _parse_x_posts(thread_text: str) -> List[Tuple[int, str]]:
    """Parse a numbered X thread, robust to both formats:
        - `1/ body on same line`
        - `1/\\nbody on next line`
    Returns [(post_num, full_post_as_published), ...] where the 'as published'
    form is always `N/ body` so length measurement is consistent regardless
    of how the LLM formatted the boundaries.
    """
    matches = list(_POST_MARKER.finditer(thread_text))
    posts = []
    for i, m in enumerate(matches):
        n = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(thread_text)
        body = thread_text[start:end].strip()
        full = f"{n}/ {body}" if body else f"{n}/"
        posts.append((int(n), full))
    return posts


def _enforce_x_thread(
    thread_text: str,
    call_claude: Callable[[str], str] = _call_claude,
    retries: int = _X_REPAIR_MAX_RETRIES,
) -> Tuple[str, List[str]]:
    """Re-prompt Claude up to `retries` times to fix posts over 280 chars.

    Returns (final_text, failures). Empty failures = success.
    Best-effort: even if repair fails after retries, the over-limit text is
    still returned so a human can edit it in Airtable.
    """
    text = thread_text
    for attempt in range(retries + 1):
        posts = _parse_x_posts(text)
        over = [(n, len(p), p) for n, p in posts if len(p) > X_HARD_LIMIT]
        if not over:
            return text, []
        if attempt == retries:
            return text, [
                f"post {n}: {l} chars (limit {X_HARD_LIMIT})" for n, l, _ in over
            ]
        over_list = "\n".join(f"- Post {n} ({l} chars): {p}" for n, l, p in over)
        repair = (
            "The following X thread posts exceeded the 280-character hard limit "
            "(counting the `N/` prefix). Rewrite ONLY these posts under 280 chars "
            "while preserving every fact and the post's role in the thread. Return "
            "the COMPLETE thread (all posts), not just the rewrites.\n\n"
            f"=== POSTS OVER LIMIT ===\n{over_list}\n\n"
            f"=== CURRENT THREAD ===\n{text}"
        )
        text = call_claude(repair)
    return text, []  # unreachable


def transform(clean: CleanText) -> TransformOutput:
    """Fire all three modules concurrently for one clean transcript."""
    guardrails = _guardrails()
    prompts: Dict[str, str] = {
        module: _load_prompt(module, clean.text, guardrails) for module in _MODULES
    }

    out = TransformOutput()
    with ThreadPoolExecutor(max_workers=len(_MODULES)) as pool:
        futures = {pool.submit(_call_claude, prompts[m]): m for m in _MODULES}
        for fut in as_completed(futures):
            module = futures[fut]
            try:
                result = fut.result()
            except Exception as exc:  # keep partial results; record the failure
                out.errors[module] = repr(exc)
                continue
            if module == "linkedin":
                out.linkedin = result
            elif module == "x_thread":
                repaired, x_failures = _enforce_x_thread(result)
                out.x_thread = repaired
                if x_failures:
                    out.errors["x_thread_280_enforce"] = "; ".join(x_failures)
            elif module == "newsletter":
                out.newsletter = result
    return out
