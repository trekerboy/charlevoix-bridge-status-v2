"""Continuous rolling ring buffer and full 720p opening cycle exporter."""
from __future__ import annotations

import collections
import json
import logging
import re
import shutil
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .config import Config

log = logging.getLogger("capture")


class CycleCaptureBuffer:
    """Maintains a rolling 120s pre-event in-memory buffer and exports full opening recordings."""

    def __init__(self, config: Config):
        self.config = config
        self.capture_dir = config.capture_dir / "events"
        self.capture_dir.mkdir(parents=True, exist_ok=True)

        self.buffer_seconds = config.pre_event_buffer_seconds
        # Target buffer size: 10 FPS * 120s = 1200 frames
        self.max_buffer_frames = config.camera_fps * self.buffer_seconds
        self.ring_buffer: collections.deque[tuple[float, bytes]] = collections.deque(maxlen=self.max_buffer_frames)

        self.active_cycle_id: str | None = None
        self.active_cycle_dir: Path | None = None
        self.cycle_start_ts: float | None = None
        self.frames_saved = 0

    def append(self, ts: float, frame_bytes: bytes):
        """Pushes a fresh 720p frame to the rolling ring buffer or active recording."""
        self.ring_buffer.append((ts, frame_bytes))

        if self.active_cycle_dir is not None:
            self._write_frame(ts, frame_bytes)

    def start_recording(self, cycle_id: str, ts: float):
        """Begins recording an active opening cycle, dumping pre-event buffer to disk."""
        if self.active_cycle_id is not None:
            log.warning("Recording already active for %s. Ignoring start for %s", self.active_cycle_id, cycle_id)
            return

        clean_id = re.sub(r"[^a-zA-Z0-9_-]", "", cycle_id)
        self.active_cycle_id = clean_id
        self.active_cycle_dir = self.capture_dir / clean_id
        self.active_cycle_dir.mkdir(parents=True, exist_ok=True)
        self.cycle_start_ts = ts
        self.frames_saved = 0

        log.info("Started opening cycle capture %s. Flushing %d pre-event frames...", clean_id, len(self.ring_buffer))

        # Dump pre-event ring buffer frames to disk
        for b_ts, b_bytes in list(self.ring_buffer):
            self._write_frame(b_ts, b_bytes)

    def stop_recording(self, metadata: dict[str, Any] | None = None):
        """Concludes active cycle recording, writes manifest.json, and enforces disk retention."""
        if self.active_cycle_id is None or self.active_cycle_dir is None:
            return

        end_ts = time.time()
        duration_s = max(0.0, end_ts - (self.cycle_start_ts or end_ts))
        manifest = {
            "id": self.active_cycle_id,
            "start_ts": self.cycle_start_ts,
            "end_ts": end_ts,
            "duration_s": round(duration_s, 2),
            "frames_count": self.frames_saved,
            "resolution": f"{self.config.camera_width}x{self.config.camera_height}",
            "metadata": metadata or {},
        }

        manifest_path = self.active_cycle_dir / "manifest.json"
        try:
            manifest_path.write_text(json.dumps(manifest, indent=2))
            log.info("Saved cycle %s manifest (%d frames, %.1fs)", self.active_cycle_id, self.frames_saved, duration_s)
        except OSError as e:
            log.error("Failed to write cycle manifest: %s", e)

        self.active_cycle_id = None
        self.active_cycle_dir = None
        self.cycle_start_ts = None
        self.frames_saved = 0

        self.prune_retention()

    def _write_frame(self, ts: float, frame_bytes: bytes):
        """Writes a single JPEG frame to the active cycle directory."""
        if self.active_cycle_dir is None:
            return
        frame_name = f"{ts:.3f}.jpg"
        fpath = self.active_cycle_dir / frame_name
        try:
            fpath.write_bytes(frame_bytes)
            self.frames_saved += 1
        except OSError as e:
            log.warning("Failed to save frame %s: %s", frame_name, e)

    def prune_retention(self):
        """Enforces FIFO disk space retention cap (e.g. 25 cycles / 2048 MB)."""
        max_cycles = self.config.capture_max_cycles
        max_bytes = self.config.capture_max_mb * 1024 * 1024

        cycle_dirs = [d for d in self.capture_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
        cycle_dirs.sort(key=lambda p: p.stat().st_mtime)

        # 1. Prune by cycle count
        while len(cycle_dirs) > max_cycles:
            oldest = cycle_dirs.pop(0)
            if not (oldest / "audit.json").exists():  # Preserve certified audits
                log.info("Pruning excess cycle directory: %s", oldest.name)
                shutil.rmtree(oldest, ignore_errors=True)

        # 2. Prune by total size
        total_size = sum(f.stat().st_size for d in cycle_dirs for f in d.glob("*") if f.is_file())
        while total_size > max_bytes and cycle_dirs:
            oldest = cycle_dirs.pop(0)
            if not (oldest / "audit.json").exists():
                dir_size = sum(f.stat().st_size for f in oldest.glob("*") if f.is_file())
                log.info("Pruning oldest cycle directory to free disk: %s (%.1f MB)", oldest.name, dir_size / (1024 * 1024))
                shutil.rmtree(oldest, ignore_errors=True)
                total_size -= dir_size
