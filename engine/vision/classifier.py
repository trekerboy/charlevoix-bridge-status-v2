"""Spatial classification and directional event derivation for roadway and channel traffic."""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Sequence

from ..config import SpatialZones
from .tracker import Track

log = logging.getLogger("classifier")


@dataclass
class CrossingEvent:
    ts: float
    kind: str          # 'vehicle', 'pedestrian', 'bicycle'
    direction: str     # 'northbound', 'southbound'
    track_id: int
    confidence: float = 1.0


@dataclass
class PassageEvent:
    ts: float
    kind: str          # 'vessel'
    direction: str     # 'inbound' (Round Lake), 'outbound' (Lake Michigan)
    track_id: int
    confidence: float = 1.0


class SpatialClassifier:
    """Evaluates track trajectories against spatial calibration zones and boundary lines."""

    def __init__(self, zones: SpatialZones, frame_width: int = 1280, frame_height: int = 720):
        self.zones = zones
        self.w = frame_width
        self.h = frame_height
        self.midline_x = zones.roadway_midline_x * frame_width

        # Deduplication caches: (track_id -> expiry_ts)
        self._counted_crossings: set[int] = set()
        self._counted_passages: set[int] = set()

    def is_seawall_or_pier(self, nx: float, ny: float) -> bool:
        """Filters out stationary non-channel zones (boardwalks, bridge tender tower, pier fenders)."""
        # South pedestrian boardwalk
        if nx > 0.43 and ny > 0.74:
            return True
        # North boardwalk / tender tower
        if nx < 0.35 and ny < 0.63:
            return True
        # North pier fender
        if nx > 0.46 and ny < 0.65:
            return True
        return False

    def in_channel(self, nx: float, ny: float) -> bool:
        """Checks if normalized coordinate lies in navigable Pine River channel."""
        c = self.zones.channel_norm
        if not (c[0] <= nx <= c[2] and c[1] <= ny <= c[3]):
            return False
        return not self.is_seawall_or_pier(nx, ny)

    def in_roadway(self, nx: float, ny: float) -> bool:
        """Checks if normalized coordinate lies on US-31 bridge deck."""
        r = self.zones.roadway_norm
        return r[0] <= nx <= r[2] and r[1] <= ny <= r[3]

    def in_sidewalk(self, nx: float, ny: float) -> bool:
        """Checks if normalized coordinate lies on north or south sidewalks."""
        far = self.zones.walk_far_norm
        near = self.zones.walk_near_norm
        if far[0] <= nx <= far[2] and far[1] <= ny <= far[3]:
            return True
        if near[0] <= nx <= near[2] and near[1] <= ny <= near[3]:
            return True
        return False

    def evaluate_tracks(
        self,
        active_tracks: Sequence[Track],
        ts: float,
    ) -> tuple[list[CrossingEvent], list[PassageEvent]]:
        """Processes active tracks and derives new crossings or vessel passages."""
        crossings: list[CrossingEvent] = []
        passages: list[PassageEvent] = []

        for track in active_tracks:
            if track.classified or len(track.history) < 2:
                continue

            first_t, first_x, first_y = track.history[0]
            last_t, last_x, last_y = track.history[-1]
            dt = max(0.1, last_t - first_t)

            dx = last_x - first_x
            dy = last_y - first_y
            dist = math.hypot(dx, dy)

            # Normalized current position
            nx = track.cx / max(1.0, self.w)
            ny = track.cy / max(1.0, self.h)

            # --- 1. Marine Vessel Classification ---
            if track.kind == "vessel" and track.track_id not in self._counted_passages:
                if self.in_channel(nx, ny) and dist >= 25.0:
                    speed = dist / dt
                    # Pine River speed limit: 35 px/s max, 0.5 px/s min to reject water ripples
                    if 0.5 <= speed <= 55.0:
                        # Channel navigation vector:
                        # Inbound toward Round Lake moves up and right (dx > 0 or dy < 0)
                        # Outbound toward Lake Michigan moves down and left (dx < 0 or dy > 0)
                        # Channel axis projection: dx - 1.2 * dy
                        axis_proj = dx - 1.2 * dy
                        direction = "inbound" if axis_proj > 0 else "outbound"

                        passages.append(
                            PassageEvent(
                                ts=ts,
                                kind="vessel",
                                direction=direction,
                                track_id=track.track_id,
                                confidence=track.score,
                            )
                        )
                        track.classified = True
                        self._counted_passages.add(track.track_id)
                        log.info("Marine vessel detected: %s (speed %.1f px/s, track #%d)", direction, speed, track.track_id)
                        continue

            # --- 2. Roadway Vehicle Classification ---
            if track.kind == "vehicle" and track.track_id not in self._counted_crossings:
                if self.in_roadway(nx, ny) and dist >= 30.0:
                    # Check if trajectory crossed midline
                    crossed_left = first_x > self.midline_x and last_x <= self.midline_x
                    crossed_right = first_x < self.midline_x and last_x >= self.midline_x

                    if crossed_left:
                        direction = "northbound"
                    elif crossed_right:
                        direction = "southbound"
                    else:
                        # Direct horizontal displacement check
                        direction = "northbound" if dx < 0 else "southbound"

                    crossings.append(
                        CrossingEvent(
                            ts=ts,
                            kind="vehicle",
                            direction=direction,
                            track_id=track.track_id,
                            confidence=track.score,
                        )
                    )
                    track.classified = True
                    self._counted_crossings.add(track.track_id)
                    log.debug("Vehicle crossing detected: %s (track #%d)", direction, track.track_id)
                    continue

            # --- 3. Pedestrians & Bicycles Classification ---
            if track.kind in ("pedestrian", "bicycle") and track.track_id not in self._counted_crossings:
                if (self.in_sidewalk(nx, ny) or self.in_roadway(nx, ny)) and dist >= 20.0:
                    direction = "northbound" if dx < 0 else "southbound"
                    crossings.append(
                        CrossingEvent(
                            ts=ts,
                            kind=track.kind,
                            direction=direction,
                            track_id=track.track_id,
                            confidence=track.score,
                        )
                    )
                    track.classified = True
                    self._counted_crossings.add(track.track_id)
                    log.debug("%s crossing detected: %s (track #%d)", track.kind.capitalize(), direction, track.track_id)
                    continue

        return crossings, passages
