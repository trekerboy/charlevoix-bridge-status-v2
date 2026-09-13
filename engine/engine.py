"""Unified Ingestion & Computer Vision Engine for NVIDIA Spark host."""
from __future__ import annotations

import logging
import os
import tempfile
import time
from dataclasses import asdict
from pathlib import Path

from .capture import CycleCaptureBuffer
from .config import Config
from .events import calculate_performance_grade, calculate_schedule_offset, get_regime
from .ingestion import MJPEGStreamReader, MockStreamReader
from .state_machine import BridgeEventCycle, BridgeStateMachine
from .store import Store
from .vision import ByteTrack, InfrastructureStateEstimator, ObjectDetector, SpatialClassifier

log = logging.getLogger("engine")


class VisionEngine:
    """Orchestrates 10-12 FPS frame ingestion, GPU vision inference, and telemetry persistence."""

    def __init__(self, config: Config, mock: bool = False):
        self.config = config
        self.mock = mock
        self._running = False

        # Ingestion
        if mock:
            self.stream = MockStreamReader(config, fps=float(config.camera_fps))
        else:
            self.stream = MJPEGStreamReader(config)

        # Store
        self.store = Store(config.db_path)

        # Vision Pipeline
        self.detector = ObjectDetector(
            model_path=config.model_path,
            device=config.device,
            conf_threshold=config.conf_threshold,
            iou_threshold=config.iou_threshold,
            mock=mock,
        )
        self.tracker = ByteTrack(high_thresh=config.conf_threshold, low_thresh=0.15)
        self.classifier = SpatialClassifier(
            zones=config.zones,
            frame_width=config.camera_width,
            frame_height=config.camera_height,
        )
        self.state_estimator = InfrastructureStateEstimator(zones=config.zones)

        # Capture & State Machine
        self.capture_buffer = CycleCaptureBuffer(config)
        self.state_machine = BridgeStateMachine(
            debounce_count=2,
            on_milestone=self._on_milestone,
            on_cycle_complete=self._on_cycle_complete,
        )

        self.last_frame_ts = 0.0
        self.fps_meter_start = time.time()
        self.frames_processed = 0

    def _on_milestone(self, kind: str, ts: float, meta: dict):
        """Callback invoked when state machine identifies a milestone transition."""
        self.store.record_milestone(ts=ts, kind=kind, source="detector", confidence=0.95)

        if kind in ("road_blocked", "lift_start") and self.capture_buffer.active_cycle_id is None:
            cycle_id = meta.get("cycle_id", f"{ts:.0f}")
            self.capture_buffer.start_recording(cycle_id, ts)

    def _on_cycle_complete(self, cycle: BridgeEventCycle):
        """Callback invoked when opening cycle completes."""
        offset_s, is_sched = calculate_schedule_offset(cycle.t_lift or time.time())
        local_dt = time.localtime(cycle.t_lift or time.time())
        import datetime as dt
        from .config import LOCAL_TZ
        dt_obj = dt.datetime.fromtimestamp(cycle.t_lift or time.time(), LOCAL_TZ)
        reg = get_regime(dt_obj)

        op_data = {
            "lift_start": cycle.t_lift or cycle.t_blocked or time.time(),
            "full_open_at": cycle.t_open,
            "lower_start": cycle.t_lower,
            "seated": cycle.t_seated,
            "rise_s": (cycle.t_open - cycle.t_lift) if (cycle.t_open and cycle.t_lift) else None,
            "hold_s": (cycle.t_lower - cycle.t_open) if (cycle.t_lower and cycle.t_open) else None,
            "lower_s": (cycle.t_seated - cycle.t_lower) if (cycle.t_seated and cycle.t_lower) else None,
            "total_s": cycle.lift_duration_s,
            "complete": 1 if cycle.peak_openness_pct >= 80 else 0,
            "max_openness": cycle.peak_openness_pct,
            "schedule_offset_s": offset_s,
            "scheduled": 1 if is_sched else 0,
            "regime": reg,
            "boats_in": cycle.boats_in,
            "boats_out": cycle.boats_out,
            "pre_opening_wait_s": cycle.pre_opening_wait_s,
            "road_closure_s": cycle.road_closure_s,
            "notes": f"Auto-detected cycle {cycle.cycle_id}",
        }
        op_data["grade_json"] = calculate_performance_grade(op_data)
        self.store.upsert_opening(op_data)

        # Stop recording after short traffic buffer
        self.capture_buffer.stop_recording(metadata=op_data)

    def run(self, max_iterations: int | None = None):
        """Main engine ingestion and processing loop."""
        self._running = True
        log.info("Starting VisionEngine on Spark host (device: %s)...", self.config.device)

        iteration = 0
        try:
            for ts, frame_bytes in self.stream.frames(max_frames=max_iterations):
                if not self._running:
                    break

                t0 = time.perf_counter()
                self.last_frame_ts = ts
                self.frames_processed += 1

                # 1. Rolling buffer & recording
                self.capture_buffer.append(ts, frame_bytes)

                # 2. Vision Inference
                detections = self.detector.detect(frame_bytes)
                active_tracks = self.tracker.update(detections, ts)

                # 3. Spatial Crossings & Passages
                crossings, passages = self.classifier.evaluate_tracks(active_tracks, ts)
                for c in crossings:
                    self.store.record_crossing(ts=c.ts, direction=c.direction, kind=c.kind, confidence=c.confidence)
                for p in passages:
                    self.store.record_boat(ts=p.ts, direction=p.direction, confidence=p.confidence)
                    if self.state_machine.active_cycle:
                        if p.direction == "inbound":
                            self.state_machine.active_cycle.boats_in += 1
                        else:
                            self.state_machine.active_cycle.boats_out += 1

                # 4. Infrastructure State & Milestones
                infra = self.state_estimator.estimate(detections)
                milestones = self.state_machine.update(
                    ts=ts,
                    leaf_state=infra.leaf_state,
                    gate_state=infra.gate_state,
                    percent_open=infra.percent_open,
                )

                # 5. Persist Reading
                latency_ms = (time.perf_counter() - t0) * 1000.0
                self.store.record_reading(
                    ts=ts,
                    state=milestones.state,
                    confidence=infra.confidence,
                    leaf_angle_deg=infra.leaf_angle_deg,
                    percent_open=infra.percent_open,
                    gate_state=milestones.gate,
                    engine="mock" if self.mock else "gpu_yolo",
                    latency_ms=round(latency_ms, 2),
                )

                # 6. Atomic live.jpg update for sub-second video feed
                self._publish_live_frame(frame_bytes)

                # 7. Periodic heartbeat (every 100 frames)
                if self.frames_processed % 100 == 0:
                    elapsed = max(0.1, time.time() - self.fps_meter_start)
                    current_fps = self.frames_processed / elapsed
                    self.store.record_health(
                        kind="engine_fps",
                        detail=f"FPS: {current_fps:.1f} | Latency: {latency_ms:.1f}ms | Tracks: {len(active_tracks)}",
                    )
                    log.info("Engine running at %.1f FPS (inference latency: %.1fms)", current_fps, latency_ms)

                iteration += 1
                if max_iterations and iteration >= max_iterations:
                    break

        except KeyboardInterrupt:
            log.info("Engine interrupted by user.")
        finally:
            self.stop()

    def _publish_live_frame(self, frame_bytes: bytes):
        """Atomically publishes live.jpg via temporary file rename to prevent partial reads."""
        live_path = self.config.live_image_path
        live_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            temp_fd, temp_path = tempfile.mkstemp(dir=live_path.parent, prefix="live_", suffix=".tmp")
            with os.fdopen(temp_fd, "wb") as f:
                f.write(frame_bytes)
            os.replace(temp_path, live_path)
        except OSError as e:
            log.warning("Failed to atomically write live frame: %s", e)

    def stop(self):
        """Stops the engine and closes open resources."""
        self._running = False
        self.stream.stop()
        self.store.close()
        log.info("VisionEngine stopped.")
