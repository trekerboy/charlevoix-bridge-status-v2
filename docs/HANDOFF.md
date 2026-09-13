# Project Handoff — Charlevoix Memorial Bridge Platform (Next-Gen)

## Master Purpose & Direction

This platform monitors the Charlevoix Memorial Bridge (bascule span carrying US-31 over the Pine River channel in Charlevoix, MI). It produces continuous, high-accuracy telemetry to power:
1. A live web dashboard and historical archive browser.
2. A web-based visual event auditor for ground-truth certification.
3. An **iOS app with a Lock-Screen / Dynamic Island Live Activity** displaying real-time bridge status (gate drops, leaf elevation, closure duration) and historical community crossing metrics.

Target environment: Dedicated **NVIDIA Spark** compute appliance (`spark-2079`, Ubuntu 24.04 ARM64, NVIDIA GB10 Blackwell GPU, CUDA 13.1, 121 GB RAM, 3.7 TB NVMe).

---

## Code Map & Component Responsibilities

| Directory / File | Responsibility |
|---|---|
| `engine/config.py` | Typed system configuration, credential masking, spatial zone calibration |
| `engine/requirements.txt` | Python runtime dependencies (Pillow, NumPy, Requests, Ultralytics) |
| `engine/ingestion.py` | Resilient HTTP Digest MJPEG stream client with exponential backoff & 401 halt |
| `engine/store.py` | SQLite WAL mode store, schema initialization, indexed analytical queries |
| `engine/vision/detector.py` | GPU deep learning detector (YOLO/RT-DETR on CUDA 13.1 / TensorRT with CPU fallback) |
| `engine/vision/tracker.py` | ByteTrack multi-object tracker (IoU matching + Kalman filter tracking) |
| `engine/vision/classifier.py` | Spatial zone mapping (US-31 NB/SB, sidewalks, channel In/Out, seawall rejection) |
| `engine/vision/state_estimator.py` | Infrastructure state estimation (barrier gates and bascule leaf elevation angle) |
| `engine/state_machine.py` | Debounced milestone derivation ($t_{\text{blocked}} \dots t_{\text{resume}}$), queue wait, closure time |
| `engine/events.py` | 33 CFR § 117.641 regulatory regime classification & A+ to F performance grading rubric |
| `engine/capture.py` | Rolling 120s ring buffer, full 720p opening cycle exporter, FIFO disk retention |
| `engine/engine.py` | Unified 10–12 FPS vision loop, atomic `live.jpg` writer, store persistence |
| `engine/api.py` | Fast API daemon on port 8090 (`/stats`, `/live`, `/captures`, `/audit`, `/recognize`) |
| `engine/main.py` | Unified CLI entrypoint (`--mode engine`, `--mode api`, `--mode all`, `--mock`) |
| `web/` | Modern Vercel frontend: live dashboard, 33-slot schedule grid, 24-hr traffic charts |
| `web/audit/` | Web Event Auditor: visual scrubber, milestone certifier, hotkey R Recognition HUD |
| `web/api/` | Vercel edge proxy routes (`stats.js`, `live.js`, `captures.js`) with edge CDN caching |
| `tools/evaluate_openings.py`| Automated zero-regression golden benchmark evaluation harness |
| `tools/sync_audits.py` | Certified audit discovery and `.golden.json` exporter |
| `docs/validation/golden/` | Certified human ground-truth benchmark datasets |
| `deploy/` | Systemd unit files (`bridgecam-next-engine`, `bridgecam-next-api`) & atomic release runner |
| `tests/` | Automated test suite verifying ingestion, vision, state machine, grading, and benchmarks |

---

## Spatial Zones Calibration (Native 1280×720 Resolution)

1. **Pine River Channel (Marine Vessels)**:
   - Navigable Water Bounding Box: $x \in [0.20, 0.65]$, $y \in [0.54, 0.95]$ normalized.
   - Channel Displacement Axis: Vector pointing up-right = Inbound (Round Lake); down-left = Outbound (Lake Michigan).
   - Seawall & Fender Pier Rejection: Rejects boardwalk detections at $(cx > 0.43, cy > 0.74)$, north tower $(cx < 0.35, cy < 0.63)$, and north fender $(cx > 0.46, cy < 0.65)$.
2. **US-31 Roadway (Vehicles)**:
   - Roadway Deck Zone: $x \in [0.20, 0.65]$, $y \in [0.44, 0.56]$ normalized.
   - Midline Crossing: Right $\to$ Left = Northbound; Left $\to$ Right = Southbound.
3. **Sidewalks (Pedestrians & Bicycles)**:
   - Far Sidewalk (North): $y \in [0.420, 0.455]$.
   - Near Sidewalk (South): $y \in [0.490, 0.545]$.
4. **Barrier Gates**:
   - Upright arm against building facade and horizontal deck arm.
5. **Bascule Leaf**:
   - Bascule rotation angle $\theta \in [0^\circ, 65^\circ]$ mapped smoothly to geometric elevation percentage.

---

## API & iOS Live Activity Contract

The Fast API daemon runs on port `8090` and provides:
- `GET /api/stats` (or `/api/stats?date=YYYY-MM-DD`): Comprehensive real-time status, active opening phases, elapsed durations, barrier gate state, 33-slot schedule grid, off-schedule lifts, and 24-hr hourly traffic buckets.
- `GET /api/live`: High-frequency, sub-second latency raw JPEG frame (<1s lag from physical camera).
- `GET /api/captures` & `/api/captures/<id>`: Manifests and frame streams for recorded opening cycles.
- `POST /api/recognize`: On-demand frame recognition HUD and telemetry payload.
- `POST /api/audit`: Ground-truth human certification persistence.

This API contract is clean, JSON-serializable, and directly consumable by the iOS Live Activity and push notification server.
