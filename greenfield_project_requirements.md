# Project Specification: Charlevoix Bridge Vision & Analytics System (Next-Gen)

> **Document Purpose:** This document serves as the foundational prompt and master technical specification for bootstrapping a clean-slate, greenfield implementation of the Charlevoix Memorial Bridge Computer Vision & Analytics Platform on a dedicated NVIDIA Spark host. It captures all operational lessons, agent governance rules, and infrastructure patterns learned from the initial prototype while completely eliminating legacy technical debt.

---

## 1. Executive Summary & Core Objective

### Objective
Build a modern, production-grade computer vision and analytics platform that monitors the **Charlevoix Memorial Bridge** (a double-leaf bascule drawbridge in Charlevoix, MI carrying US-31 over the Pine River channel) using a live Axis network camera feed.

The system extracts continuous, reliable real-time and historical telemetry:
1. **Bridge Openings & Road Closure:** Precise milestones (gates dropping, leaf lift start, peak openness %, leaf seated, gates clearing, traffic resuming), wait-before-lift duration, total road closure time, and 33 CFR § 117.641 regulatory compliance.
2. **Channel Marine Traffic:** Vessel counts and navigation directions (Round Lake inbound vs. Lake Michigan outbound) both during active bridge openings (tall craft) and under the closed span (~16 ft clearance) 24/7.
3. **Cross-Bridge Roadway & Sidewalk Traffic:** Directional vehicle counts (US-31 northbound vs. southbound), pedestrians, and bicycles.
4. **Live Dashboard & Auditor UI:** A fast, modern web frontend providing real-time bridge status, low-latency live camera view, historical date archives, 33-slot schedule grid, and an integrated visual event auditor for ground-truth certification.

### Foundational Shift from Legacy Prototype
The original prototype was architected around the severe limits of a free-tier 0.5-core Oracle Cloud VM. That constrained environment forced fragmented compromises: dual polling processes, classical background-subtraction differencing, night pixel-dilation hacks, template matching on building walls, downscaled 360p video, and turning off night boat tracking due to water glare.

This new project starts from scratch targeting a dedicated **NVIDIA Spark** compute appliance with an **NVIDIA GB10 Blackwell GPU**, running modern deep learning models on GPU 24/7 at native resolution, completely abandoning classical CV heuristics.

---

## 2. Target Hardware & Infrastructure Specifications

| Component | Specification |
|---|---|
| **Host System** | NVIDIA Spark (`spark-2079`), Ubuntu 24.04 LTS (ARM64) |
| **GPU / Acceleration** | NVIDIA GB10 Blackwell GPU, CUDA 13.1, TensorRT / PyTorch |
| **Memory & Storage** | 121 GB Unified RAM, 3.7 TB NVMe SSD |
| **Networking & Ingress** | Tailscale node (`100.81.82.120`), Tailscale Funnel for public HTTPS proxy |
| **Runtime User & Path** | User: `jason`, Base path: `/home/jason/bridgecam-next` (or designated app dir) |
| **Frontend Hosting** | Vercel (Hobby/Pro), deploying directly from the GitHub repository `main` branch |
| **Deployment Mechanism** | GitHub Actions running automated test suite followed by restricted SSH release |

---

## 3. Legacy Coexistence & Decommissioning Playbook

A legacy prototype is currently operational on this Spark machine. The new system must be developed, staged, and benchmarked without disrupting existing monitoring until the operator approves final cutover.

### Legacy Inventory on Spark Host
- **App Directory:** `/home/jason/bridgecam/app`
- **Data & Databases:** `/home/jason/bridgecam/data` (`bridge.db`, `captures/`, `active_learning/`)
- **Config & Secrets:** `/home/jason/bridgecam/config/bridgecam.env`
- **Active User Services (`systemctl --user`):**
  - `bridgecam-poller.service`
  - `bridgecam-counter.service`
  - `bridgecam-dashboard.service` (listening on `127.0.0.1:8085`)
  - `bridgecam-events.timer` & `bridgecam-events.service`
  - `ollama-vlm.service` (listening on `127.0.0.1:11435`)

### Staging Rules for New Project
1. **Isolated Filesystem:** Install the new project in `/home/jason/bridgecam-next` (app) and `/home/jason/bridgecam-next/data` (storage).
2. **Dedicated Port:** Bind the new dashboard/API service to a distinct port (e.g. `127.0.0.1:8090` or `8088`).
3. **Dedicated Service Names:** Name systemd services with a clear prefix (e.g., `bridgecam-next-engine.service`, `bridgecam-next-api.service`).

### Clean Decommissioning Sequence (Execute Only Upon Cutover Approval)
```bash
# 1. Stop and disable all legacy services
systemctl --user stop bridgecam-poller bridgecam-counter bridgecam-dashboard bridgecam-flywheel.timer bridgecam-events.timer
systemctl --user disable bridgecam-poller bridgecam-counter bridgecam-dashboard bridgecam-flywheel.timer bridgecam-events.timer

# 2. Archive legacy SQLite and capture data to cold storage
mkdir -p /home/jason/legacy-bridgecam-archive
cp -r /home/jason/bridgecam/data /home/jason/legacy-bridgecam-archive/

# 3. Switch Tailscale Funnel / port routing to the new service port (e.g. 8090 -> 8443)
# 4. Enable and start new production services
systemctl --user enable --now bridgecam-next-engine bridgecam-next-api
```

---

## 4. System Architecture & High-Level Design

```text
               ┌────────────────────────────────────────────────────────┐
               │         Axis Network Community Camera (Charlevoix)     │
               └───────────────────────────┬────────────────────────────┘
                                           │ Single HTTP MJPEG stream (Native 720p)
                                           ▼
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│                          NVIDIA Spark (`spark-2079`)                                      │
│                                                                                           │
│   ┌───────────────────────────────────────────────────────────────────────────────────┐   │
│   │ Unified Vision & Ingestion Engine (`bridgecam-next-engine`)                       │   │
│   │                                                                                   │   │
│   │   1. Stream Ingest: Resilient HTTP Digest MJPEG client (10–12 FPS, Native 720p)   │   │
│   │   2. Deep Learning Vision (GB10 Blackwell GPU / TensorRT / CUDA 13.1):           │   │
│   │      - Multi-Object Tracking (YOLOv8/v11 + ByteTrack on GPU)                      │   │
│   │        * Vehicles (NB/SB), Pedestrians, Bicycles (sidewalks)                      │   │
│   │        * Marine Vessels (Inbound/Outbound Round Lake Channel, 24/7 Day & Night)   │   │
│   │      - Infrastructure State Estimation:                                           │   │
│   │        * Barricade gate detection (raised / lowered / transitioning)              │   │
│   │        * Bridge leaf elevation & bascule angle (seated / lifting / full / lowering)│  │
│   │   3. State Machine & Event Derivation:                                            │   │
│   │      - Debounced milestone derivation (road_blocked, lift_start, seated, clear)   │   │
│   │      - Pre-opening vehicle queue wait & road closure duration calculation         │   │
│   │   4. Continuous Capture Ring Buffer:                                              │   │
│   │      - Rolling in-memory buffer (120s pre-event)                                  │   │
│   │      - Full opening cycle exporter (100% 720p frames with metadata for auditing)  │   │
│   │   5. Atomic Publisher:                                                            │   │
│   │      - Writes `live.jpg` (low latency raw feed, <1s lag)                          │   │
│   │      - Persists crossings, milestones & telemetry to SQLite (WAL mode)            │   │
│   └──────────────────────────────────────┬────────────────────────────────────────────┘   │
│                                          │                                                │
│                                          ▼                                                │
│   ┌───────────────────────────────────────────────────────────────────────────────────┐   │
│   │ Fast API & Telemetry Daemon (`bridgecam-next-api` on port 8090)                   │   │
│   │   - GET /api/stats (Live snapshot + historical ?date=YYYY-MM-DD)                  │   │
│   │   - GET /api/live (Sub-second low-latency raw camera frame)                       │   │
│   │   - GET /api/captures & /api/captures/<id> (Event video replay manifests)         │   │
│   │   - POST /api/audit (Persist human ground-truth certifications)                   │   │
│   │   - POST /api/recognize (Instant single-frame recognition HUD & telemetry inspect)│   │
│   └──────────────────────────────────────┬────────────────────────────────────────────┘   │
└──────────────────────────────────────────┼────────────────────────────────────────────────┘
                                           │ Tailscale Funnel (HTTPS)
                                           ▼
┌───────────────────────────────────────────────────────────────────────────────────────────┐
│                              Vercel Web Platform                                          │
│                                                                                           │
│   ┌───────────────────────────────────────────────┐  ┌────────────────────────────────┐   │
│   │ Live Public Dashboard                         │  │ Event Auditor & Ground Truth   │   │
│   │ - 2s live bridge status & low-lag video player│  │ - Frame-by-frame visual audit  │   │
│   │ - 33-slot daytime schedule grid (33 CFR)      │  │ - Milestone certification      │   │
│   │ - 24-hr traffic & marine distribution charts  │  │ - Single-Frame HUD Inspector   │   │
│   │ - Historical date navigation & edge caching   │  │ - Golden benchmark exporter    │   │
│   └───────────────────────────────────────────────┘  └────────────────────────────────┘   │
└───────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. Camera Integration & Ingestion Protocol

1. **Camera Specifications & Etiquette:**
   - Source: Axis Communications Fixed Community Network Camera overlooking Charlevoix Memorial Bridge.
   - Authentication: HTTP Digest Authentication over HTTPS/HTTP.
   - Credentials: Must be loaded strictly from ignored environment files (`.env`). **Never print, log, or commit camera credentials or URLs.**
   - Protocol Decision: **Single HTTP MJPEG Stream.** To eliminate RTSP port forwarding and firewall hurdles on the community network while avoiding duplicate streams, connect to a single stream at native resolution (1280×720) at 10–12 FPS.
2. **Resilience & Backoff:**
   - Implement exponential backoff with jitter on network disconnections or transient camera errors.
   - If HTTP 401 Unauthorized occurs, halt immediately to prevent account lockout.
   - The engine must buffer frames smoothly; a dropped network packet must not crash the tracking pipeline.

---

## 6. Vision Engine & Model Requirements

The vision engine must exploit the **NVIDIA GB10 Blackwell GPU** directly via PyTorch or TensorRT with CUDA 13.1. 

### Model Strategy
- **Framework:** Ultralytics YOLOv8 / YOLOv11 or RT-DETR, exported to TensorRT / ONNX with `CUDAExecutionProvider`.
- **Target Classes:**
  1. `vessel` (boats, sailboats, yachts, catamarans, tenders, ferries, kayaks in channel water)
  2. `vehicle` (cars, trucks, vans, buses, motorcycles on US-31 roadway)
  3. `pedestrian` (people on north and south sidewalks)
  4. `bicycle` (cyclists on sidewalks or roadway)
  5. `barrier_gate` (road closure arm in raised / lowered state)
  6. `leaf_span` (bridge leaf bascule orientation / angle)
- **Elimination of Classical Fallbacks:**
  - **No background subtraction:** Do not use contour differencing or union-find connected components.
  - **24/7 Uniform Processing:** Day and night frames run through the exact same deep learning detector. Headlights, illuminated water, and shadows are handled natively by model weights.
  - **Continuous Marine Tracking:** Vessel tracking remains active 24/7 across all bridge states (both during lifts and under the closed ~16 ft span). The deep learning detector will not hallucinate boats from headlight reflections on dark water.
- **Multi-Object Tracking (MOT):**
  - Use **ByteTrack** running on GPU detection outputs.
  - Directional vector classification:
    - Roadway: Crossing mid-span line right→left = Northbound; left→right = Southbound.
    - Channel: Displacement along channel axis up-right = Inbound (Round Lake); down-left = Outbound (Lake Michigan).
    - Spatial Seawall Rejection: Ignore detections on pedestrian boardwalks or fender piers.

---

## 7. Bridge Event & Regulatory Logic

The system must automatically derive physical bridge milestones and evaluate performance according to federal regulations:

1. **Milestone Sequence:**
   - $t_{\text{blocked}}$: Barricade gates lower, blocking roadway traffic.
   - $t_{\text{lift}}$: Bridge leaves begin angular ascent.
   - $t_{\text{open}}$: Leaves reach peak openness (up to ~75°).
   - $t_{\text{lower}}$: Leaves begin downward motion.
   - $t_{\text{seated}}$: Leaves fully seat and lock in the deck cradle.
   - $t_{\text{clear}}$: Barricade gates fully rise.
   - $t_{\text{resume}}$: First vehicle crosses after clearing.
2. **Key Derived Metrics:**
   - **Pre-Opening Wait:** $t_{\text{lift}} - t_{\text{blocked}}$ (the frustrating wait while gates are down before bridge moves).
   - **Total Road Closure Duration:** $t_{\text{clear}} - t_{\text{blocked}}$.
   - **Lift Duration:** $t_{\text{seated}} - t_{\text{lift}}$.
3. **Regulatory Regime (33 CFR § 117.641):**
   - Scheduled Regime (April 1 – Oct 31, 6:00 AM – 10:00 PM): Lifts for recreational craft occur on the hour (:00) and half-hour (:30).
   - Commercial / On-Demand: Lifts for commercial vessels, government craft, or off-season happen on signal.
   - Schedule Adherence: Flag punctuality offsets relative to the scheduled slot.
4. **Academic Performance Grading (A+ to F):**
   - Evaluate operator efficiency balancing punctuality, marine throughput, proportional lift height, and minimized vehicle road closure delay.

---

## 8. Frontend & Visual Auditor Architecture

A completely clean, modern web application built for high performance, accessibility, and visual clarity:

1. **Tech Stack & Deployment:**
   - Modern, lightweight frontend deployed on Vercel from the repository root.
   - Communicates with the Spark backend via secure HTTPS proxy routes (e.g. `/api/stats`, `/api/live`, `/api/captures`).
   - Edge CDN caching for historical, immutable date snapshots (`Cache-Control: public, s-maxage=86400`).
2. **Dashboard Features (`/`):**
   - **Live Bridge Status:** Visual leaf angle gauge, gate status, current state duration, and last reading freshness.
   - **Low-Latency Live View:** Sub-second live camera stream player with toggle to full-screen mode.
   - **33-Slot Schedule Infographic:** Interactive timeline of daily opening slots (:00 and :30), indicating completed lifts, active lifts, upcoming windows, or uncalled slots.
   - **Off-Schedule Separation:** Unscheduled commercial lifts display in a dedicated card section without colliding with scheduled slots.
   - **Traffic & Channel Distribution Charts:** 24-hour visual analytics showing vehicle flow (NB/SB), pedestrians, cyclists, and channel boat passages.
   - **Historical Date Navigator:** Seamless browsing of past calendar days with clean URL sync (`?date=YYYY-MM-DD`).
3. **Web Auditor UI (`/audit`):**
   - **Visual Event Scrubber:** Frame-by-frame scrubbing through recorded opening cycles.
   - **Ground-Truth Certification Controls:** Reviewers mark exact milestone timestamps, record vessel tallies, and add notes.
   - **Single-Frame Recognition HUD (Hotkey `R`):** On-demand inspection that draws bounding boxes, confidence scores, and detection metadata directly over any video frame.
   - **Dual Persistence:** Automatically saves drafts to `localStorage` and commits certified records to the backend SQLite store.

---

## 9. Ground-Truth Certification & Zero-Regression Benchmarking Gate

Accuracy cannot be assumed; it must be proven on real recorded footage.

1. **Golden Dataset Creation:**
   - Ground truth is established by human visual review using the Auditor UI.
   - Certified events are exported as version-controlled JSON records: `docs/validation/golden/<event_id>.golden.json`.
2. **Mandatory Automated Benchmark Gate:**
   - Implement an evaluation harness (`tools/evaluate_openings.py`) and CI test suite (`tests/test_accuracy_benchmarks.py`).
   - Before deploying any model, threshold, or tracking logic update, the test suite replays all certified golden audits.
3. **The Zero-Regression Rule:**
   - **Milestone Timing Tolerance:** $|\Delta t| \le 3.0\text{s}$ against certified human timestamps.
   - **Vessel Count Accuracy:** 100% exact match on vessel counts across all certified openings.
   - **Mandatory Policy:** If a change degrades accuracy or causes regressions on certified benchmarks, **deployment is prohibited**. The agent must inspect failing frames, iterate on detection logic, and re-benchmark until baseline is met or exceeded.

---

## 10. CI/CD, Deployment & Ops Architecture

1. **GitHub Actions Continuous Deployment:**
   - Any push to `main` executes unit tests and benchmark validations.
   - Backend changes trigger a secure, restricted SSH release to `spark-2079`.
   - Release workflow performs atomic symlink switching (`/home/jason/bridgecam-next/current`), executes post-deploy health checks (verifying API liveness and fresh camera frames), and automatically rolls back if health checks fail.
   - Frontend changes deploy automatically via Vercel GitHub integration.
2. **Persistence & Data Integrity:**
   - Use **SQLite in WAL mode** (`PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;`).
   - Preserve database and calibration state across releases; code releases must never overwrite runtime databases.
   - Schema updates must be strictly additive and backward compatible.

---

## 11. Agent-Facing Standards & Governance Rules

Any coding agent working in this repository must strictly adhere to the following rules:

1. **Mandatory Documentation Synchronization:**
   - This repository is the handoff source of truth across LLM sessions.
   - Whenever you introduce endpoints, alter calibration, add components, or modify behavior, you **MUST** update `README.md`, `docs/HANDOFF.md`, and `docs/OPERATIONS.md`. Never leave documentation stale.
2. **Credential & Secret Protection:**
   - Never commit passwords, `.env` files, SSH keys, private URLs, or raw camera environment variables.
   - Redact all sensitive camera IP/URLs in diagnostic logs and test outputs.
3. **Validation Honesty:**
   - Synthetic tests or single-frame tests do not prove night, weather, or boat accuracy.
   - Always benchmark against real multi-frame recorded events using certified golden ground truth.
4. **Code Quality Gates:**
   - Run unit test suite: `python -m unittest discover -s tests -v`.
   - Run formatting/lint checks: `git diff --check`.
   - For UI changes, verify responsiveness, accessibility, reduced-motion preferences, and live updates in a real browser.

---

## 12. Phased Implementation Roadmap

* **Phase 1: Foundation & Camera Ingestion**
  - Scaffold project structure, environment configuration, and logging.
  - Implement resilient 720p HTTP MJPEG camera ingestion client with digest auth.
  - Set up SQLite schema with WAL mode and atomic `live.jpg` writer.
* **Phase 2: Deep Learning Vision Pipeline on Spark GPU**
  - Integrate YOLOv8/v11 on CUDA 13.1 / TensorRT.
  - Implement ByteTrack multi-object tracking for vehicles, vessels, pedestrians, and cyclists.
  - Implement direct state detection for barricade gates and bridge leaf elevation.
* **Phase 3: Event Engine & Capture Ring Buffer**
  - Build rolling 120s pre-event buffer and automatic opening cycle recorder.
  - Implement debounced state machine for 33 CFR § 117.641 milestones and wait times.
  - Implement operator efficiency grading algorithm.
* **Phase 4: Fast API & Web Auditor Tooling**
  - Expose read-only endpoints: `/api/stats`, `/api/live`, `/api/captures`, `/api/recognize`.
  - Build the Web Event Auditor (`/audit`) with frame scrubber and milestone certifier.
  - Build the automated golden benchmark evaluation harness.
* **Phase 5: Modern Web Dashboard**
  - Build fresh frontend on Vercel with real-time status and sub-second video.
  - Implement 33-slot schedule grid, off-schedule cards, and 24-hr traffic charts.
  - Implement historical date navigation with edge caching.
* **Phase 6: CI/CD & Production Cutover**
  - Set up GitHub Actions CI with automated benchmark gates.
  - Set up restricted SSH deployment to `spark-2079`.
  - Perform parallel verification against legacy system, then execute the decommissioning playbook.
