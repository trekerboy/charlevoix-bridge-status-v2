#!/usr/bin/env python3
"""Discovers human-certified audits in captures directory and syncs them to docs/validation/golden/"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("sync_audits")


def sync_audits(captures_dir: Path, golden_dir: Path):
    golden_dir.mkdir(parents=True, exist_ok=True)
    events_dir = captures_dir / "events" if (captures_dir / "events").exists() else captures_dir

    audit_files = list(events_dir.glob("**/audit.json"))
    log.info("Found %d audit.json files in %s", len(audit_files), events_dir)

    synced = 0
    for af in audit_files:
        try:
            data = json.loads(af.read_text())
            event_id = data.get("event_id", af.parent.name)
            target = golden_dir / f"{event_id}.golden.json"
            target.write_text(json.dumps(data, indent=2))
            log.info("Synced: %s -> %s", af.name, target.name)
            synced += 1
        except Exception as e:
            log.warning("Failed to sync %s: %s", af, e)

    log.info("Successfully synced %d certified audits.", synced)


def main():
    parser = argparse.ArgumentParser(description="Sync certified audits to golden benchmarks")
    parser.add_argument("--captures", default="data/captures", help="Captures directory")
    parser.add_argument("--golden", default="docs/validation/golden", help="Golden directory")
    args = parser.parse_args()
    sync_audits(Path(args.captures), Path(args.golden))


if __name__ == "__main__":
    main()
