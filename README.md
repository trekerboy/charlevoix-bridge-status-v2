# Charlevoix Memorial Bridge Vision & Analytics Platform (Next-Gen)

A modern, production-grade computer vision and real-time telemetry platform monitoring the **Charlevoix Memorial Bridge** (double-leaf bascule bridge carrying US-31 over the Pine River channel in Charlevoix, Michigan) from an Axis network camera.

Designed to power a real-time web dashboard, visual event auditor, and ultimately an **iOS app featuring a Lock-Screen / Dynamic Island Live Activity**.

---

## System Architecture

```text
Axis Network Camera (720p MJPEG)
       │ HTTP Digest Auth (10–12 FPS native)
       ▼
NVIDIA Spark (`spark-2079`, GB10 Blackwell GPU, CUDA 13.1)
  ┌─────────────────────────────────────────────────────────────┐
  │ Unified Vision Engine (`bridgecam-next-engine`)             │
  │  - Deep Learning Detection: YOLO / ByteTrack 24/7 on GPU   │
  │    * Marine Vessels (Round Lake Inbound vs Lake MI Outbound)│
  │    * Roadway Vehicles (US-31 NB / SB)                      │
  │    * Pedestrians & Bicycles (North / South Sidewalks)       │
  │    * Infrastructure: Barrier Gates & Bascule Elevation      │
  │  - Debounced Physical Milestone Derivation                  │
  │  - Rolling 120s Pre-Event Capture Ring Buffer               │
  │  - Atomic Publisher: `live.jpg` (<1s lag) + SQLite WAL Mode │
  └──────────────────────────────┬──────────────────────────────┘
                                 │
                                 ▼
  ┌─────────────────────────────────────────────────────────────┐
  │ Fast API & Telemetry Daemon (`bridgecam-next-api`: 8090)    │
  │  - GET  /api/stats (Live snapshot + historical ?date=)      │
  │  - GET  /api/live (Sub-second low-latency raw camera frame) │
  │  - GET  /api/captures & /api/captures/<id>                  │
  │  - POST /api/audit (Commit human ground truth)              │
  │  - POST /api/recognize (Instant single-frame inspection HUD)│
  └──────────────────────────────┬──────────────────────────────┘
                                 │ Tailscale Funnel HTTPS
                                 ▼
Vercel Edge Platform / iOS Client
  ┌──────────────────────────────┴──────────────────────────────┐
  │ 1. Public Dashboard (`/`)                                   │
  │    - Sub-second live view, 33-slot schedule grid,           │
  │      off-schedule cards, 24-hr traffic volume analytics     │
  │ 2. Visual Event Auditor (`/audit`)                          │
  │    - Frame-by-frame scrubber, hotkey R Recognition HUD,     │
  │      dual persistence, golden dataset benchmark exporter    │
  │ 3. Future iOS App & Live Activity Engine                    │
  └─────────────────────────────────────────────────────────────┘
```

---

## Key Telemetry & Features

1. **Bridge Openings & Road Closure**:
   - Milestones: $t_{\text{blocked}}$ (gates drop), $t_{\text{lift}}$ (leaf elevation begins), $t_{\text{open}}$ (peak openness %), $t_{\text{lower}}$ (descent begins), $t_{\text{seated}}$ (leaf cradle locked), $t_{\text{clear}}$ (gates upright), and $t_{\text{resume}}$ (first vehicle crossing).
   - Metrics: Pre-opening queue wait ($t_{\text{lift}} - t_{\text{blocked}}$) and total road closure duration ($t_{\text{clear}} - t_{\text{blocked}}$).
   - Regulatory Regime (33 CFR § 117.641): Scheduled :00/:30 slots vs. commercial/government on-signal lifts.
   - Academic Grading (A+ to F): Operator efficiency rubric balancing punctuality, marine volume, transit efficiency, and swift proportional lift bonuses.
2. **Channel Marine Traffic**:
   - Vessel counts and directional flow (Inbound to Round Lake vs. Outbound to Lake Michigan) tracked 24/7 across all bridge states (both during lifts and under the closed ~16 ft span).
3. **Cross-Bridge Traffic**:
   - Directional vehicle crossings (Northbound vs. Southbound US-31), pedestrians, and cyclists on dedicated sidewalk zones.
4. **Zero-Regression Benchmark Gate**:
   - Every algorithm or threshold update is automatically tested against version-controlled golden datasets (`tests/test_accuracy_benchmarks.py`).

---

## Quickstart

### Prerequisites
- Python 3.10+ (production: Ubuntu 24.04 / Python 3.12, ARM64)
- Node.js 20+ (for Vercel edge routes)

### Local Setup
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r engine/requirements.txt

# Run unit and benchmark tests
python3 -m unittest discover -s tests -v

# Run local mock engine and API
python3 -m engine.main --mock --port 8090
```

---

## Agent Handoff & Continuity
See [AGENTS.md](AGENTS.md) and [docs/HANDOFF.md](docs/HANDOFF.md).
