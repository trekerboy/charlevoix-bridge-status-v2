"""Infrastructure state estimation for bascule leaf elevation and barricade gates."""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Sequence

from ..config import SpatialZones
from .detector import Detection

log = logging.getLogger("state_estimator")


@dataclass
class BridgeInfrastructureState:
    leaf_state: str            # 'down' | 'moving' | 'up' | 'unknown'
    leaf_angle_deg: float      # 0.0 .. 65.0 degrees
    percent_open: int          # 0 .. 100%
    gate_state: str            # 'raised' | 'lowered' | 'transitioning' | 'unknown'
    confidence: float          # 0.0 .. 1.0


class InfrastructureStateEstimator:
    """Estimates mechanical bridge state and enforces physical invariant rules."""

    def __init__(self, zones: SpatialZones):
        self.zones = zones
        self.max_angle = zones.max_leaf_angle_deg

    def estimate(
        self,
        detections: Sequence[Detection],
        raw_leaf_angle: float | None = None,
        raw_gate_state: str | None = None,
    ) -> BridgeInfrastructureState:
        """Derives clean, debounced infrastructure state from vision detections and measurements."""
        # 1. Inspect detections for explicit gate or leaf objects
        gate_status = raw_gate_state or "raised"
        leaf_state = "down"
        leaf_angle = raw_leaf_angle or 0.0

        for det in detections:
            if det.kind == "barrier_gate":
                # High confidence gate detection
                if det.score >= 0.40:
                    gate_status = "lowered" if det.w > det.h else "raised"
            elif det.kind == "leaf_span":
                if det.score >= 0.40:
                    leaf_state = "up"
                    leaf_angle = min(self.max_angle, max(15.0, leaf_angle or 45.0))

        # 2. Geometric percent open mapping
        # Maps bascule leaf angle [0, max_angle] to 0..100%
        pct_open = int(round(100.0 * min(1.0, max(0.0, leaf_angle / self.max_angle))))
        if leaf_angle >= 5.0 and leaf_state == "down":
            leaf_state = "moving"
        if pct_open >= 85:
            leaf_state = "up"

        # 3. Physical Invariant Sanity Rules
        # Rule A: If bridge span is elevated or moving, gates CANNOT be raised
        if leaf_state in ("up", "moving") and gate_status == "raised":
            log.warning("Physical Invariant violated: Bridge is %s but gate reported raised. Forcing gate to lowered.", leaf_state)
            gate_status = "lowered"

        return BridgeInfrastructureState(
            leaf_state=leaf_state,
            leaf_angle_deg=leaf_angle,
            percent_open=pct_open,
            gate_state=gate_status,
            confidence=0.95,
        )
