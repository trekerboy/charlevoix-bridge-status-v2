#!/usr/bin/env bash
set -euo pipefail

echo "==> Setting up Charlevoix Bridge Next-Gen on Spark Host..."
BASE_DIR="/home/jason/bridgecam-next"
mkdir -p "${BASE_DIR}/releases" "${BASE_DIR}/data/captures/events" "${BASE_DIR}/config"

if [ ! -d "${BASE_DIR}/venv" ]; then
    echo "==> Creating Python 3 virtual environment..."
    python3 -m venv "${BASE_DIR}/venv"
    "${BASE_DIR}/venv/bin/pip" install --upgrade pip
    "${BASE_DIR}/venv/bin/pip" install pillow numpy requests ultralytics
fi

echo "==> Installing systemd user services..."
mkdir -p ~/.config/systemd/user
cp deploy/bridgecam-next-*.service ~/.config/systemd/user/
systemctl --user daemon-reload

echo "==> Host setup complete. Ready for staged deployment on port 8090."
