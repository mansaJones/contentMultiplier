# Style Guardrails

This file is injected into every Claude transform prompt. Per Phase 5 of the blueprint,
update it frequently with examples of copy mistakes so the models stop repeating them.

## Voice
- Plain, direct, human. Write like a smart colleague, not a press release.
- No corporate filler: "leverage", "synergy", "in today's fast-paced world", "game-changer".

## Banned phrases / patterns (add to this list as you spot them)
- "I'm thrilled to announce"
- "Let that sink in."
- Emoji-bulleted lists (🚀✅🔥) unless explicitly on-brand.
- Fake-engagement bait ("Agree? 👇", "Thoughts?")

## Formatting rules
- LinkedIn: short paragraphs, line breaks for scannability, ONE clear CTA.
- X thread: hard 280-char cap per post, numbered, hook in post 1, payoff at the end.
- Newsletter: editorial teaser — curiosity gap, do NOT give away the full payoff.

## Factual integrity
- Never invent statistics, names, dates, or quotes not present in the source transcript.
- If a number appears in the source, preserve it exactly. If unsure, omit it.
