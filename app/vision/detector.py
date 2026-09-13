"""GPU-accelerated Deep Learning Object Detector targeting NVIDIA GB10 Blackwell."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence
from PIL import Image

log = logging.getLogger("detector")


@dataclass
class Detection:
    kind: str          # 'vehicle', 'vessel', 'pedestrian', 'bicycle', 'barrier_gate', 'leaf_span'
    score: float       # 0.0 .. 1.0
    box: tuple[float, float, float, float]  # [x1, y1, x2, y2] in pixels
    cx: float          # center x
    cy: float          # center y
    w: float           # width
    h: float           # height
    area: float        # w * h


# Mapping from standard COCO class IDs / names to our unified schema
COCO_MAPPING = {
    "car": "vehicle",
    "truck": "vehicle",
    "bus": "vehicle",
    "motorcycle": "vehicle",
    "person": "pedestrian",
    "bicycle": "bicycle",
    "boat": "vessel",
}


class ObjectDetector:
    """Deep learning detector supporting Ultralytics YOLOv8/v11, ONNX Runtime, and mock mode."""

    def __init__(
        self,
        model_path: str | Path = "models/yolov8n.pt",
        device: str = "cuda:0",
        conf_threshold: float = 0.35,
        iou_threshold: float = 0.50,
        mock: bool = False,
    ):
        self.model_path = Path(model_path)
        self.device = device
        self.conf_threshold = conf_threshold
        self.iou_threshold = iou_threshold
        self.mock = mock
        self._model = None
        self._backend = "mock" if mock else "unloaded"

        if not mock:
            self._load_model()

    def _load_model(self):
        """Attempts to load PyTorch/Ultralytics GPU model, falling back gracefully."""
        if not self.model_path.exists():
            log.warning("Model file not found at %s. Falling back to mock detection mode.", self.model_path)
            self._backend = "mock"
            return

        try:
            from ultralytics import YOLO
            log.info("Loading YOLO model on device %s from %s...", self.device, self.model_path)
            self._model = YOLO(str(self.model_path))
            # Test inference / warm up
            self._backend = "ultralytics"
            log.info("Successfully loaded YOLO model on %s.", self.device)
        except Exception as e:
            log.warning("Failed to load YOLO model (%s). Operating in fallback mode.", e)
            self._backend = "fallback"

    def detect(self, image: Image.Image | bytes) -> list[Detection]:
        """Runs object detection on a 720p frame, returning standardized Detections."""
        if isinstance(image, bytes):
            import io
            image = Image.open(io.BytesIO(image)).convert("RGB")

        w, h = image.size

        if self._backend == "ultralytics" and self._model is not None:
            try:
                results = self._model.predict(
                    source=image,
                    device=self.device,
                    conf=self.conf_threshold,
                    iou=self.iou_threshold,
                    verbose=False,
                )
                detections: list[Detection] = []
                for r in results:
                    boxes = r.boxes
                    for b in boxes:
                        cls_id = int(b.cls[0])
                        raw_name = r.names.get(cls_id, str(cls_id)).lower()
                        kind = COCO_MAPPING.get(raw_name, raw_name)
                        score = float(b.conf[0])
                        xyxy = [float(coord) for coord in b.xyxy[0]]
                        x1, y1, x2, y2 = xyxy
                        bx_w = max(1.0, x2 - x1)
                        bx_h = max(1.0, y2 - y1)
                        cx = x1 + bx_w / 2.0
                        cy = y1 + bx_h / 2.0

                        detections.append(
                            Detection(
                                kind=kind,
                                score=score,
                                box=(x1, y1, x2, y2),
                                cx=cx,
                                cy=cy,
                                w=bx_w,
                                h=bx_h,
                                area=bx_w * bx_h,
                            )
                        )
                return detections
            except Exception as e:
                log.error("GPU inference error: %s. Returning empty detections.", e)
                return []

        # Mock detections for CI / test validation
        return []
