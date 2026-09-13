#!/usr/bin/env python3
"""Atomic Symlink Release Runner with Health Checks & Rollback."""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("release")


def run_cmd(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    log.info("Running: %s", " ".join(cmd))
    return subprocess.run(cmd, check=check, text=True, capture_output=True)


def check_health(port: int = 8090, timeout_s: float = 30.0) -> bool:
    """Verifies that the newly deployed API daemon responds with healthy telemetry."""
    deadline = time.time() + timeout_s
    url = f"http://127.0.0.1:{port}/stats"
    log.info("Checking API health at %s (timeout: %.0fs)...", url, timeout_s)

    while time.time() < deadline:
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                if resp.status == 200:
                    log.info("Health check passed! API daemon responded HTTP 200.")
                    return True
        except Exception:
            time.sleep(1.0)

    log.error("Health check timed out after %.0fs", timeout_s)
    return False


def deploy(base_dir: Path, source_dir: Path, port: int = 8090):
    base_dir = base_dir.resolve()
    releases_dir = base_dir / "releases"
    current_link = base_dir / "current"
    releases_dir.mkdir(parents=True, exist_ok=True)

    release_name = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
    target_dir = releases_dir / release_name

    log.info("Creating new release directory: %s", target_dir)
    shutil.copytree(source_dir, target_dir, ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__", "data"))

    # Save previous release for rollback
    prev_release = None
    if current_link.is_symlink():
        prev_release = current_link.resolve()

    # Atomic symlink switch
    temp_link = base_dir / f"link_{release_name}"
    os.symlink(target_dir, temp_link)
    os.replace(temp_link, current_link)
    log.info("Switched current symlink to %s", release_name)

    # Restart services
    log.info("Restarting systemd services...")
    run_cmd(["systemctl", "--user", "restart", "bridgecam-next-engine.service", "bridgecam-next-api.service"], check=False)

    # Post-deployment health verification
    if not check_health(port=port):
        log.critical("DEPLOYMENT HEALTH CHECK FAILED! Initiating automatic rollback...")
        if prev_release and prev_release.is_dir():
            os.symlink(prev_release, temp_link)
            os.replace(temp_link, current_link)
            run_cmd(["systemctl", "--user", "restart", "bridgecam-next-engine.service", "bridgecam-next-api.service"], check=False)
            log.info("Successfully rolled back to %s", prev_release.name)
        sys.exit(1)

    log.info("Deployment %s completed successfully!", release_name)


def main():
    parser = argparse.ArgumentParser(description="Charlevoix Bridge Release Runner")
    parser.add_argument("--base", default="/home/jason/bridgecam-next", help="Base deployment directory")
    parser.add_argument("--source", default=".", help="Source tree to release")
    parser.add_argument("--port", type=int, default=8090, help="API health check port")
    args = parser.parse_args()

    deploy(Path(args.base), Path(args.source), port=args.port)


if __name__ == "__main__":
    main()
