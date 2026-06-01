"""Content Multiplier CLI.

Usage:
    python main.py ingest     # Phase 1->3: ingest new Drive assets, transform, stage
    python main.py publish    # Phase 4: distribute approved Airtable records as Buffer drafts
    python main.py channels   # one-time: list Buffer channels (for .env channel IDs)
    python main.py loop       # run ingest+publish continuously on an interval

Run `ingest` and `publish` on separate schedules (e.g. ingest every 15 min,
publish every 5 min) or use `loop` for a simple always-on process.
"""

from __future__ import annotations

import argparse
import logging
import time

from content_multiplier import distribute, pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("content_multiplier.cli")


def main() -> None:
    parser = argparse.ArgumentParser(description="Automated Cross-Platform Content Multiplier")
    parser.add_argument("command", choices=["ingest", "publish", "channels", "loop"])
    parser.add_argument(
        "--interval", type=int, default=300, help="loop sleep seconds (default 300)"
    )
    args = parser.parse_args()

    if args.command == "ingest":
        n = pipeline.run_ingest_cycle()
        log.info("Ingest cycle complete: %d asset(s) staged.", n)
    elif args.command == "publish":
        n = pipeline.run_publish_cycle()
        log.info("Publish cycle complete: %d record(s) distributed.", n)
    elif args.command == "channels":
        channels = distribute.list_channels()
        if not channels:
            log.info("No Buffer channels found for this API key.")
        else:
            log.info("Found %d channel(s). Paste the IDs you need into .env:", len(channels))
            for ch in channels:
                print(f"  {ch.get('service','?'):>12}  {ch.get('id','?')}  {ch.get('name','?')}")
    elif args.command == "loop":
        log.info("Starting loop with %ds interval. Ctrl-C to stop.", args.interval)
        while True:
            try:
                staged = pipeline.run_ingest_cycle()
                published = pipeline.run_publish_cycle()
                log.info("Cycle: %d staged, %d published.", staged, published)
            except Exception:
                log.exception("Cycle failed; continuing.")
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
