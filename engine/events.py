"""33 CFR § 117.641 Regulatory Regime, Schedule Adherence, and Performance Grading."""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any
from zoneinfo import ZoneInfo

from .config import LOCAL_TZ

log = logging.getLogger("events")


def get_regime(local_dt: dt.datetime) -> str:
    """Returns governing federal regulation under 33 CFR § 117.641.

    Regimes:
      - 'restricted': Apr 1 - Oct 31, 06:00-22:00 EDT/EST (:00 and :30 recreational slots).
      - 'on_signal': Apr 1 - Dec 31 outside 06:00-22:00 (nights and all of Nov-Dec).
      - 'advance_notice': Jan 1 - Mar 31 (12h advance notice required).
    """
    m, h = local_dt.month, local_dt.hour
    if m <= 3:
        return "advance_notice"
    if 4 <= m <= 10 and 6 <= h < 22:
        return "restricted"
    return "on_signal"


def calculate_schedule_offset(lift_start_ts: float) -> tuple[float, bool]:
    """Calculates offset in seconds from nearest :00 or :30 slot, and whether it was scheduled."""
    local_dt = dt.datetime.fromtimestamp(lift_start_ts, LOCAL_TZ)
    minute = local_dt.minute
    second = local_dt.second

    # Nearest slot minute is either 0 or 30
    if minute < 15:
        target_min = 0
    elif minute < 45:
        target_min = 30
    else:
        target_min = 60

    slot_dt = local_dt.replace(minute=0, second=0, microsecond=0)
    if target_min == 30:
        slot_dt = slot_dt.replace(minute=30)
    elif target_min == 60:
        slot_dt = slot_dt + dt.timedelta(hours=1)

    offset_s = (local_dt - slot_dt).total_seconds()
    # 33 CFR window is +/- 3 minutes, allow up to +/- 5m (300s) for scheduled classification
    is_scheduled = (get_regime(local_dt) == "restricted") and (abs(offset_s) <= 300.0)

    return offset_s, is_scheduled


def calculate_performance_grade(opening: dict[str, Any]) -> dict[str, Any]:
    """Computes academic performance grade (A+ through F) using operator efficiency rubric."""
    score = 100
    reasons: list[str] = []

    lift_start = opening.get("lift_start")
    if not lift_start:
        return {"score": 100, "letter": "A+", "summary": "Unrated"}

    local_dt = dt.datetime.fromtimestamp(lift_start, LOCAL_TZ)
    reg = opening.get("regime") or get_regime(local_dt)
    offset_s, is_scheduled = calculate_schedule_offset(lift_start)

    # 1. Schedule Adherence (Punctuality)
    if reg == "restricted":
        abs_off = abs(offset_s)
        if abs_off <= 90:
            reasons.append("Punctual slot adherence")
        elif abs_off <= 180:
            score -= 5
            reasons.append("Minor schedule drift (-5)")
        elif abs_off <= 300:
            score -= 15
            reasons.append("Moderate schedule offset (-15)")
        else:
            score -= 25
            reasons.append("Off-schedule lift (-25)")
    else:
        reasons.append("On-signal priority opening")

    # 2. Marine Volume & Clearance Stewardship
    boats_in = opening.get("boats_in", 0) or 0
    boats_out = opening.get("boats_out", 0) or 0
    total_boats = boats_in + boats_out
    plural = "s" if total_boats != 1 else ""

    duration_s = opening.get("road_closure_s") or opening.get("total_s") or 120.0
    pct_open = opening.get("max_openness", 100)
    is_partial_lift = 0 < pct_open <= 75
    is_swift_cycle = duration_s <= 135.0

    if total_boats == 0:
        if is_swift_cycle or is_partial_lift:
            score -= 10
            reasons.append("0 boats observed · swift clearance (-10)")
        else:
            score -= 25
            reasons.append("0 boats observed (-25)")
    elif total_boats >= 8:
        score += 10
        reasons.append(f"High volume convoy ({total_boats} boats, +10)")
    elif total_boats >= 4:
        score += 5
        reasons.append(f"Multi-vessel convoy ({total_boats} boats, +5)")
    elif is_swift_cycle or is_partial_lift:
        score += 5
        lift_type = "Swift proportional lift" if is_partial_lift else "Swift proportional clearance"
        reasons.append(f"{total_boats} boat{plural} passed · {lift_type} (+5)")
    else:
        reasons.append(f"{total_boats} boat{plural} passed")

    # 3. Productive Transit vs Dead Dwell Duration
    if duration_s is not None:
        effective_boats = max(1, total_boats)
        expected_s = 110.0 + effective_boats * 30.0
        excess_s = max(0.0, duration_s - expected_s)

        if excess_s <= 60:
            reasons.append(f"Efficient transit ({duration_s/60:.1f}m vs ~{expected_s/60:.1f}m expected)")
        elif excess_s <= 120:
            score -= 5
            reasons.append(f"Minor hold slack (+{excess_s:.0f}s, -5)")
        elif excess_s <= 180:
            score -= 15
            reasons.append(f"Extended hold (+{excess_s:.0f}s, -15)")
        elif excess_s <= 300:
            score -= 30
            reasons.append(f"Protracted delay (+{excess_s:.0f}s, -30)")
        else:
            score -= 45
            reasons.append(f"Severe excess dwell (+{excess_s:.0f}s, -45)")

        if duration_s > 600:
            score -= 10
            reasons.append("Extended closure >10m (-10)")

    score = max(0, min(100, score))

    if score >= 97:
        letter = "A+"
    elif score >= 93:
        letter = "A"
    elif score >= 90:
        letter = "A-"
    elif score >= 87:
        letter = "B+"
    elif score >= 83:
        letter = "B"
    elif score >= 80:
        letter = "B-"
    elif score >= 77:
        letter = "C+"
    elif score >= 73:
        letter = "C"
    elif score >= 70:
        letter = "C-"
    elif score >= 60:
        letter = "D"
    else:
        letter = "F"

    return {
        "score": score,
        "letter": letter,
        "summary": " · ".join(reasons),
        "total_boats": total_boats,
        "duration_s": duration_s,
    }
