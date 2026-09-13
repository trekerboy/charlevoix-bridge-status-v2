"""Unified CLI entrypoint for Charlevoix Bridge Vision Engine and API Daemon."""
from __future__ import annotations

import argparse
import logging
import threading
from pathlib import Path

from .api import run_api_daemon
from .config import Config
from .engine import VisionEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")


def main():
    parser = argparse.ArgumentParser(description="Charlevoix Memorial Bridge Vision & Analytics Platform (Next-Gen)")
    parser.add_argument("--mode", choices=["engine", "api", "all"], default="all", help="Service mode to run")
    parser.add_argument("--mock", action="store_true", help="Run with mock stream reader and detectors")
    parser.add_argument("--port", type=int, default=None, help="HTTP API port (default: 8090 or APP_PORT env)")
    parser.add_argument("--max-iterations", type=int, default=None, help="Stop engine after N iterations")
    parser.add_argument("--db", type=str, default=None, help="Path to SQLite database")

    args = parser.parse_args()
    config = Config()

    if args.port:
        config.app_port = args.port
    if args.db:
        config.db_path = Path(args.db)

    log.info("Initializing Charlevoix Bridgecam Next-Gen (mode: %s, mock: %s)...", args.mode, args.mock)

    if args.mode == "engine":
        engine = VisionEngine(config, mock=args.mock)
        engine.run(max_iterations=args.max_iterations)

    elif args.mode == "api":
        run_api_daemon(config)

    elif args.mode == "all":
        # Launch API daemon in background thread, run engine on main thread
        api_thread = threading.Thread(target=run_api_daemon, args=(config,), daemon=True)
        api_thread.start()

        engine = VisionEngine(config, mock=args.mock)
        engine.run(max_iterations=args.max_iterations)


if __name__ == "__main__":
    main()
