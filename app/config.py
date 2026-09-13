"""Typed configuration and environment management for Charlevoix Bridgecam Next-Gen."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("America/Detroit")

def _get_bool(key: str, default: bool) -> bool:
    val = os.environ.get(key)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")

def _get_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, default))
    except (ValueError, TypeError):
        return default

def _get_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except (ValueError, TypeError):
        return default


@dataclass(frozen=True)
class SpatialZones:
    """Normalized bounding zones in native 1280x720 camera coordinates."""
    # Marine channel navigable water [x_min, y_min, x_max, y_max]
    channel_norm: tuple[float, float, float, float] = (0.20, 0.54, 0.65, 0.95)
    # Roadway US-31 span
    roadway_norm: tuple[float, float, float, float] = (0.20, 0.44, 0.65, 0.56)
    # Sidewalks
    walk_far_norm: tuple[float, float, float, float] = (0.20, 0.420, 0.65, 0.455)
    walk_near_norm: tuple[float, float, float, float] = (0.20, 0.490, 0.65, 0.545)
    # Channel displacement vector along axis: positive = Inbound (Round Lake), negative = Outbound (Lake MI)
    # Mid-span crossing line X (normalized)
    roadway_midline_x: float = 0.425
    # Bascule max rotation angle in degrees
    max_leaf_angle_deg: float = 65.0


@dataclass
class Config:
    """Application runtime configuration."""
    # Camera Stream
    camera_host: str = field(default_factory=lambda: os.environ.get("CAMERA_HOST", "127.0.0.1"))
    camera_port: int = field(default_factory=lambda: _get_int("CAMERA_PORT", 80))
    camera_stream_path: str = field(default_factory=lambda: os.environ.get("CAMERA_STREAM_PATH", "/mjpg/video.mjpg"))
    camera_user: str = field(default_factory=lambda: os.environ.get("CAMERA_USER", ""))
    camera_pass: str = field(default_factory=lambda: os.environ.get("CAMERA_PASS", ""))
    camera_use_https: bool = field(default_factory=lambda: _get_bool("CAMERA_USE_HTTPS", False))
    camera_fps: int = field(default_factory=lambda: _get_int("CAMERA_FPS", 10))
    camera_width: int = field(default_factory=lambda: _get_int("CAMERA_WIDTH", 1280))
    camera_height: int = field(default_factory=lambda: _get_int("CAMERA_HEIGHT", 720))

    # Host & Server
    app_host: str = field(default_factory=lambda: os.environ.get("APP_HOST", "0.0.0.0"))
    app_port: int = field(default_factory=lambda: _get_int("APP_PORT", 8090))
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("DATA_DIR", "data")))
    capture_dir: Path = field(default_factory=lambda: Path(os.environ.get("CAPTURE_DIR", "data/captures")))
    db_path: Path = field(default_factory=lambda: Path(os.environ.get("DB_PATH", "data/bridge.db")))
    live_image_path: Path = field(default_factory=lambda: Path(os.environ.get("LIVE_IMAGE_PATH", "data/live.jpg")))

    # Vision & Deep Learning (GB10 Blackwell GPU on Spark)
    device: str = field(default_factory=lambda: os.environ.get("DEVICE", "cuda:0"))
    model_path: str = field(default_factory=lambda: os.environ.get("MODEL_PATH", "models/yolov8n.pt"))
    conf_threshold: float = field(default_factory=lambda: _get_float("CONF_THRESHOLD", 0.35))
    iou_threshold: float = field(default_factory=lambda: _get_float("IOU_THRESHOLD", 0.50))

    # Storage & Ring Buffer Retention
    capture_max_cycles: int = field(default_factory=lambda: _get_int("CAPTURE_MAX_CYCLES", 25))
    capture_max_mb: int = field(default_factory=lambda: _get_int("CAPTURE_MAX_MB", 2048))
    pre_event_buffer_seconds: int = field(default_factory=lambda: _get_int("PRE_EVENT_BUFFER_SECONDS", 120))

    # Spatial zones
    zones: SpatialZones = field(default_factory=SpatialZones)

    def __post_init__(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.capture_dir.mkdir(parents=True, exist_ok=True)

    @property
    def camera_url(self) -> str:
        proto = "https" if self.camera_use_https else "http"
        port_str = f":{self.camera_port}" if (self.camera_port != 80 and self.camera_port != 443) else ""
        return f"{proto}://{self.camera_host}{port_str}{self.camera_stream_path}"

    def safe_dict(self) -> dict:
        """Returns diagnostic dict with credentials strictly redacted."""
        return {
            "camera_host": self.camera_host,
            "camera_port": self.camera_port,
            "camera_user": "***" if self.camera_user else "",
            "camera_fps": self.camera_fps,
            "app_port": self.app_port,
            "device": self.device,
            "model_path": self.model_path,
            "data_dir": str(self.data_dir),
            "capture_max_mb": self.capture_max_mb,
        }

    def __repr__(self) -> str:
        return f"Config({self.safe_dict()})"
