# Agent Governance & Development Protocol

Welcome, coding agent. This repository contains the Next-Generation **Charlevoix Memorial Bridge Vision & Analytics Platform** (`charlevoix-bridge-status-v2`).

## Master Mandate & Ultimate End Goal

The ultimate end goal of this system is to power a high-performance **iOS app** featuring an interactive **Lock-Screen / Dynamic Island Live Activity** that reflects the real-time bridge status (gates lowering, lifting, percent open, lowering, seated, traffic resuming) with sub-second latency. Inside the app, users will explore rich live and historical analytics: roadway vehicle flow, marine channel vessel passages (Round Lake inbound vs. Lake Michigan outbound), pedestrians, cyclists, wait times, and regulatory compliance under 33 CFR § 117.641.

Because an iOS Live Activity and mobile alerts demand absolute trustworthiness, our computer vision recognition pipeline must be **robust, accurate, reliable, and sturdy**. All data derived from visuals must be certified and accurate.

---

## Agent Handoff & Continuity Rules

The human operator switches between different LLMs and models. **Any LLM must be able to pick up right where the previous one left off without conversational context loss.**

1. **Mandatory Documentation Synchronization**:
   - Every time you introduce endpoints, alter calibration/zones, add components, or modify behavior, you **MUST** update `README.md`, `docs/HANDOFF.md`, and `docs/OPERATIONS.md`.
   - Never leave documentation stale or incomplete.
2. **Credential & Secret Protection**:
   - Never commit passwords, `.env` files, SSH keys, private camera URLs, or credentials.
   - Redact all sensitive camera IP/URLs in diagnostic logs and test outputs.
3. **Hardware Efficiency on NVIDIA Spark**:
   - The production host is a dedicated NVIDIA Spark (`spark-2079`) with an NVIDIA GB10 Blackwell GPU and 121 GB RAM.
   - **Do not take the beefy hardware for granted.** Write optimal, high-performance code:
     - Keep hot vision loops lean with minimal memory allocations.
     - Use SQLite WAL mode with indexed queries.
     - Maintain bounded ring buffers (120s pre-event buffer, 25-cycle / 2GB FIFO retention).
     - Maintain sub-second latency for live frame distribution.
4. **Validation Honesty & Benchmark Gates**:
   - Synthetic or single-frame tests do not prove 24/7 night, weather, or marine accuracy.
   - Always run the automated benchmark gate against certified golden ground truth (`tests/test_accuracy_benchmarks.py`).
   - The Zero-Regression Rule: Milestone timing $|\Delta t| \le 3.0\text{s}$, 100% vessel count match.
5. **Quality Gates Before Handoff**:
   - Run unit tests: `python3 -m unittest discover -s tests -v`.
   - Check git cleanliness: `git diff --check`.
