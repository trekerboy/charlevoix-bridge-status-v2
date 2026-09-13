"""ByteTrack Multi-Object Tracker."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Sequence

from .detector import Detection

log = logging.getLogger("tracker")


def compute_iou(boxA: Sequence[float], boxB: Sequence[float]) -> float:
    """Computes Intersection-over-Union between two [x1, y1, x2, y2] boxes."""
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[2], boxB[2])
    yB = min(boxA[3], boxB[3])

    inter_w = max(0.0, xB - xA)
    inter_h = max(0.0, yB - yA)
    inter_area = inter_w * inter_h

    boxAArea = max(1.0, (boxA[2] - boxA[0]) * (boxA[3] - boxA[1]))
    boxBArea = max(1.0, (boxB[2] - boxB[0]) * (boxB[3] - boxB[1]))

    return inter_area / float(boxAArea + boxBArea - inter_area)


@dataclass
class Track:
    track_id: int
    kind: str
    box: tuple[float, float, float, float]
    cx: float
    cy: float
    score: float
    start_ts: float
    last_ts: float
    time_since_update: int = 0
    history: list[tuple[float, float, float]] = field(default_factory=list)  # (ts, cx, cy)
    classified: bool = False

    def update(self, det: Detection, ts: float):
        self.box = det.box
        self.cx = det.cx
        self.cy = det.cy
        self.score = det.score
        self.last_ts = ts
        self.time_since_update = 0
        self.history.append((ts, det.cx, det.cy))
        # Keep maximum of 60 points of history
        if len(self.history) > 60:
            self.history.pop(0)


class ByteTrack:
    """Multi-object tracker implementing two-stage high/low confidence IoU association."""

    def __init__(
        self,
        high_thresh: float = 0.50,
        low_thresh: float = 0.15,
        match_thresh: float = 0.30,
        max_time_lost: int = 15,
    ):
        self.high_thresh = high_thresh
        self.low_thresh = low_thresh
        self.match_thresh = match_thresh
        self.max_time_lost = max_time_lost
        self._next_id = 1
        self.tracks: list[Track] = []

    def update(self, detections: list[Detection], ts: float) -> list[Track]:
        """Updates tracker state with new frame detections."""
        # 1. Split detections into high and low confidence pools
        high_dets = [d for d in detections if d.score >= self.high_thresh]
        low_dets = [d for d in detections if self.low_thresh <= d.score < self.high_thresh]

        for t in self.tracks:
            t.time_since_update += 1

        unmatched_tracks: list[Track] = []
        unmatched_high_dets: list[Detection] = []

        # 2. First Stage Association (Active Tracks <-> High Confidence Detections)
        matched_track_indices = set()
        matched_det_indices = set()

        # Build IoU matrix for active tracks and high dets of the same kind
        for t_idx, track in enumerate(self.tracks):
            best_iou = self.match_thresh
            best_d_idx = -1
            for d_idx, det in enumerate(high_dets):
                if d_idx in matched_det_indices or track.kind != det.kind:
                    continue
                iou = compute_iou(track.box, det.box)
                if iou > best_iou:
                    best_iou = iou
                    best_d_idx = d_idx

            if best_d_idx != -1:
                track.update(high_dets[best_d_idx], ts)
                matched_track_indices.add(t_idx)
                matched_det_indices.add(best_d_idx)
            else:
                unmatched_tracks.append(track)

        for d_idx, det in enumerate(high_dets):
            if d_idx not in matched_det_indices:
                unmatched_high_dets.append(det)

        # 3. Second Stage Association (Unmatched Tracks <-> Low Confidence Detections)
        still_unmatched_tracks: list[Track] = []
        matched_low_indices = set()

        for track in unmatched_tracks:
            best_iou = self.match_thresh
            best_d_idx = -1
            for d_idx, det in enumerate(low_dets):
                if d_idx in matched_low_indices or track.kind != det.kind:
                    continue
                iou = compute_iou(track.box, det.box)
                if iou > best_iou:
                    best_iou = iou
                    best_d_idx = d_idx

            if best_d_idx != -1:
                track.update(low_dets[best_d_idx], ts)
                matched_low_indices.add(d_idx)
            else:
                still_unmatched_tracks.append(track)

        # 4. Initiate New Tracks for Remaining Unmatched High Detections
        for det in unmatched_high_dets:
            new_track = Track(
                track_id=self._next_id,
                kind=det.kind,
                box=det.box,
                cx=det.cx,
                cy=det.cy,
                score=det.score,
                start_ts=ts,
                last_ts=ts,
                time_since_update=0,
                history=[(ts, det.cx, det.cy)],
            )
            self._next_id += 1
            self.tracks.append(new_track)

        # 5. Prune Dead Tracks
        self.tracks = [t for t in self.tracks if t.time_since_update <= self.max_time_lost]

        # Return currently active tracks (updated this frame)
        return [t for t in self.tracks if t.time_since_update == 0]
