"""Debounced bridge state machine and physical milestone derivation."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

log = logging.getLogger("state_machine")


@dataclass
class BridgeEventCycle:
    """Represents an ongoing or completed bridge opening cycle."""
    cycle_id: str
    t_blocked: float | None = None
    t_lift: float | None = None
    t_open: float | None = None
    t_lower: float | None = None
    t_seated: float | None = None
    t_clear: float | None = None
    t_resume: float | None = None
    peak_openness_pct: int = 0
    boats_in: int = 0
    boats_out: int = 0
    active: bool = True

    @property
    def pre_opening_wait_s(self) -> float | None:
        """Wait time while gates are down before leaves begin lifting."""
        if self.t_lift and self.t_blocked:
            return max(0.0, self.t_lift - self.t_blocked)
        return None

    @property
    def road_closure_s(self) -> float | None:
        """Total time vehicular traffic is stopped by gates."""
        if self.t_clear and self.t_blocked:
            return max(0.0, self.t_clear - self.t_blocked)
        return None

    @property
    def lift_duration_s(self) -> float | None:
        """Duration from leaf motion start to seated lock."""
        if self.t_seated and self.t_lift:
            return max(0.0, self.t_seated - self.t_lift)
        return None


class BridgeStateMachine:
    """Debounces noisy sensor readings and tracks physical milestone transitions."""

    def __init__(
        self,
        debounce_count: int = 2,
        on_milestone: Callable[[str, float, dict], None] | None = None,
        on_cycle_complete: Callable[[BridgeEventCycle], None] | None = None,
    ):
        self.debounce_count = debounce_count
        self.on_milestone = on_milestone
        self.on_cycle_complete = on_cycle_complete

        # Running state debouncers
        self.current_state = "down"
        self.current_gate = "raised"
        self._candidate_state = "down"
        self._state_count = 0
        self._candidate_gate = "raised"
        self._gate_count = 0

        # Current active opening cycle
        self.active_cycle: BridgeEventCycle | None = None

    def update(
        self,
        ts: float,
        leaf_state: str,
        gate_state: str,
        percent_open: int = 0,
    ) -> BridgeInfrastructureMilestones:
        """Processes current frame observation and emits any milestone transitions."""
        milestones_fired: list[str] = []

        # 1. Debounce gate state
        if gate_state == self._candidate_gate:
            self._gate_count += 1
        else:
            self._candidate_gate = gate_state
            self._gate_count = 1

        if self._gate_count >= self.debounce_count and self._candidate_gate != self.current_gate:
            prev_gate = self.current_gate
            self.current_gate = self._candidate_gate
            log.info("Gate state transition: %s -> %s (at %.2f)", prev_gate, self.current_gate, ts)

            if self.current_gate == "lowered":
                if self.active_cycle is None:
                    import datetime as dt
                    from .config import LOCAL_TZ
                    cid = dt.datetime.fromtimestamp(ts, LOCAL_TZ).strftime("%Y%m%d-%H%M%SZ")
                    self.active_cycle = BridgeEventCycle(cycle_id=cid, t_blocked=ts)
                elif self.active_cycle.t_blocked is None:
                    self.active_cycle.t_blocked = ts

                milestones_fired.append("road_blocked")
                if self.on_milestone:
                    self.on_milestone("road_blocked", ts, {"cycle_id": self.active_cycle.cycle_id})

            elif self.current_gate == "raised" and self.active_cycle is not None:
                if self.active_cycle.t_clear is None:
                    self.active_cycle.t_clear = ts
                    milestones_fired.append("road_clear")
                    if self.on_milestone:
                        self.on_milestone("road_clear", ts, {"cycle_id": self.active_cycle.cycle_id})

        # 2. Debounce leaf state
        if leaf_state == self._candidate_state:
            self._state_count += 1
        else:
            self._candidate_state = leaf_state
            self._state_count = 1

        if self._state_count >= self.debounce_count and self._candidate_state != self.current_state:
            prev_state = self.current_state
            self.current_state = self._candidate_state
            log.info("Leaf state transition: %s -> %s (at %.2f)", prev_state, self.current_state, ts)

            if self.current_state in ("up", "moving") and prev_state == "down":
                if self.active_cycle is None:
                    import datetime as dt
                    from .config import LOCAL_TZ
                    cid = dt.datetime.fromtimestamp(ts, LOCAL_TZ).strftime("%Y%m%d-%H%M%SZ")
                    self.active_cycle = BridgeEventCycle(cycle_id=cid, t_lift=ts)
                elif self.active_cycle.t_lift is None:
                    self.active_cycle.t_lift = ts

                milestones_fired.append("lift_start")
                if self.on_milestone:
                    self.on_milestone("lift_start", ts, {"cycle_id": self.active_cycle.cycle_id})

            elif self.current_state == "down" and prev_state in ("up", "moving") and self.active_cycle is not None:
                if self.active_cycle.t_seated is None:
                    self.active_cycle.t_seated = ts
                    milestones_fired.append("seated")
                    if self.on_milestone:
                        self.on_milestone("seated", ts, {"cycle_id": self.active_cycle.cycle_id})

        # 3. Peak openness tracking
        if self.active_cycle is not None:
            if percent_open > self.active_cycle.peak_openness_pct:
                self.active_cycle.peak_openness_pct = percent_open
                if percent_open >= 85 and self.active_cycle.t_open is None:
                    self.active_cycle.t_open = ts
                    milestones_fired.append("full_open")
                    if self.on_milestone:
                        self.on_milestone("full_open", ts, {"cycle_id": self.active_cycle.cycle_id})

            # Check for cycle conclusion (seated and gates clear)
            if self.active_cycle.t_seated is not None and self.current_gate == "raised":
                self.active_cycle.active = False
                completed = self.active_cycle
                self.active_cycle = None
                log.info("Bridge opening cycle %s complete! Closure: %.1fs", completed.cycle_id, completed.road_closure_s or 0.0)
                if self.on_cycle_complete:
                    self.on_cycle_complete(completed)

        return BridgeInfrastructureMilestones(
            state=self.current_state,
            gate=self.current_gate,
            milestones_fired=milestones_fired,
            active_cycle=self.active_cycle,
        )


@dataclass
class BridgeInfrastructureMilestones:
    state: str
    gate: str
    milestones_fired: list[str] = field(default_factory=list)
    active_cycle: BridgeEventCycle | None = None
