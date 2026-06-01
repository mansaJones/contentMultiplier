"""Content Multiplier — automated cross-platform content pipeline.

Phases:
    1. ingest      — watch Drive, transcribe (Whisper) or parse (markdown)
    2. transform   — three concurrent Claude modules (LinkedIn / X / Newsletter)
    3. approval    — push drafts to Airtable Kanban, gate on human review
    4. distribute  — on approval, fan out to scheduler (Buffer / webhook)
"""

__version__ = "0.1.0"
