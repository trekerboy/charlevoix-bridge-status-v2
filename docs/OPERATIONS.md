# Operations & Deployment Guide

## Production Environment Overview

- **Host Machine:** NVIDIA Spark (`spark-2079`), Ubuntu 24.04 LTS (ARM64)
- **Acceleration:** NVIDIA GB10 Blackwell GPU, CUDA 13.1, PyTorch / TensorRT
- **Memory & Storage:** 121 GB Unified RAM, 3.7 TB NVMe SSD
- **Network Ingress:** Tailscale node (`100.81.82.120`), Tailscale Funnel HTTPS proxy
- **Runtime User:** `jason`
- **Application Path:** `/home/jason/bridgecam-next`
- **Data Storage:** `/home/jason/bridgecam-next/data` (`bridge.db`, `captures/`)
- **Systemd User Services:**
  - `bridgecam-next-engine.service` (Ingestion & GPU Vision loop)
  - `bridgecam-next-api.service` (Fast API Daemon on port `8090`)

---

## Legacy Coexistence & Safe Cutover Playbook

A legacy prototype is currently operational on `spark-2079` (`/home/jason/bridgecam/app`, port `8085`).
The Next-Gen system operates in parallel without conflict:
- Legacy runs on port `8085`; Next-Gen runs on port `8090`.
- Service names use `bridgecam-next-*` prefixes.
- Data directories are isolated (`/home/jason/bridgecam-next/data`).

### Clean Decommissioning Sequence (Execute Only After Cutover Approval)

```bash
# 1. Stop and disable legacy prototype services
systemctl --user stop bridgecam-poller bridgecam-counter bridgecam-dashboard bridgecam-flywheel.timer bridgecam-events.timer
systemctl --user disable bridgecam-poller bridgecam-counter bridgecam-dashboard bridgecam-flywheel.timer bridgecam-events.timer

# 2. Archive legacy SQLite and capture data to cold storage
mkdir -p /home/jason/legacy-bridgecam-archive
cp -r /home/jason/bridgecam/data /home/jason/legacy-bridgecam-archive/

# 3. Update Tailscale Funnel / port routing to point to port 8090
tailscale funnel --https=8443 8090

# 4. Ensure new production services are enabled and running
systemctl --user enable --now bridgecam-next-engine bridgecam-next-api
```

---

## Deployment & Rollback Architecture

Automated deployments use atomic symlink switching (`/home/jason/bridgecam-next/current`):
1. **GitHub Actions Workflow** triggers upon push to `main`.
2. Runs unit test suite (`python3 -m unittest discover -s tests -v`) and benchmark gates.
3. Packages code release and pushes to `spark-2079` via restricted SSH.
4. Switches current symlink, restarts `systemctl --user restart bridgecam-next-engine bridgecam-next-api`.
5. Executes post-deployment health check:
   - Verifies `http://127.0.0.1:8090/stats` returns HTTP 200 with fresh timestamp.
   - Verifies `live.jpg` is updating.
6. If health check fails within 30 seconds, automatically rolls back symlink to previous release.
