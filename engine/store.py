"""SQLite storage engine with WAL mode for telemetry, crossings, and bridge milestones."""
from __future__ import annotations

import datetime as dt
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .config import LOCAL_TZ

log = logging.getLogger("store")

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS readings (
    ts REAL PRIMARY KEY,
    iso TEXT NOT NULL,
    state TEXT NOT NULL,                -- 'down' | 'up' | 'moving' | 'unknown'
    confidence REAL NOT NULL,
    leaf_angle_deg REAL,                -- estimated bascule angle in degrees
    percent_open INTEGER,               -- 0..100%
    gate_state TEXT,                    -- 'raised' | 'lowered' | 'transitioning' | 'unknown'
    engine TEXT,                        -- 'gpu_yolo' | 'mock'
    latency_ms REAL
);
CREATE INDEX IF NOT EXISTS idx_readings_state_ts ON readings(state, ts);

CREATE TABLE IF NOT EXISTS road_milestones (
    ts REAL NOT NULL,
    iso TEXT NOT NULL,
    kind TEXT NOT NULL,                 -- 'road_blocked' | 'lift_start' | 'full_open' | 'lower_start' | 'seated' | 'road_clear' | 'traffic_resumed'
    source TEXT NOT NULL,               -- 'detector' | 'human_audit'
    confidence REAL NOT NULL,
    validated INTEGER NOT NULL DEFAULT 0,
    opening_id INTEGER,
    UNIQUE(ts, kind, source)
);
CREATE INDEX IF NOT EXISTS idx_milestones_ts ON road_milestones(ts);

CREATE TABLE IF NOT EXISTS openings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lift_start REAL NOT NULL UNIQUE,
    full_open_at REAL,
    lower_start REAL,
    seated REAL,
    rise_s REAL,
    hold_s REAL,
    lower_s REAL,
    total_s REAL,
    complete INTEGER DEFAULT 0,
    max_openness REAL,
    schedule_offset_s REAL,
    scheduled INTEGER DEFAULT 0,
    regime TEXT,                        -- 'restricted' | 'on_signal' | 'advance_notice' (33 CFR 117.641)
    boats_in INTEGER DEFAULT 0,
    boats_out INTEGER DEFAULT 0,
    pre_opening_wait_s REAL,            -- t_lift - t_blocked
    road_closure_s REAL,                -- t_clear - t_blocked
    clearance_lag_s REAL,               -- seated -> first vehicle
    grade_json TEXT,                    -- Academic grade evaluation JSON
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_openings_lift_start ON openings(lift_start);

CREATE TABLE IF NOT EXISTS vehicle_crossings (
    ts REAL NOT NULL,
    iso TEXT NOT NULL,
    direction TEXT NOT NULL,            -- 'northbound' | 'southbound'
    lane TEXT,
    kind TEXT DEFAULT 'vehicle',        -- 'vehicle' | 'pedestrian' | 'bicycle'
    confidence REAL
);
CREATE INDEX IF NOT EXISTS idx_vc_ts ON vehicle_crossings(ts);

CREATE TABLE IF NOT EXISTS boat_passages (
    ts REAL NOT NULL,
    iso TEXT NOT NULL,
    direction TEXT NOT NULL,            -- 'inbound' (Round Lake) | 'outbound' (Lake Michigan)
    opening_id INTEGER,
    confidence REAL
);
CREATE INDEX IF NOT EXISTS idx_bp_ts ON boat_passages(ts);

CREATE TABLE IF NOT EXISTS health (
    ts REAL PRIMARY KEY,
    iso TEXT NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT
);
"""


def to_iso(ts: float) -> str:
    """Returns ISO-8601 formatted string in local time."""
    return dt.datetime.fromtimestamp(ts, LOCAL_TZ).isoformat(timespec="seconds")


class Store:
    """High-performance SQLite database store with WAL mode."""

    def __init__(self, db_path: str | Path = "data/bridge.db"):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(
            str(self.path),
            isolation_level=None,
            check_same_thread=False,
            timeout=10.0,
        )
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        with self.conn:
            self.conn.executescript(SCHEMA)

    def record_reading(
        self,
        ts: float,
        state: str,
        confidence: float,
        leaf_angle_deg: float | None = None,
        percent_open: int | None = None,
        gate_state: str | None = None,
        engine: str = "gpu_yolo",
        latency_ms: float | None = None,
    ):
        """Persists a physical bridge reading."""
        self.conn.execute(
            "INSERT OR REPLACE INTO readings "
            "(ts, iso, state, confidence, leaf_angle_deg, percent_open, gate_state, engine, latency_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ts, to_iso(ts), state, float(confidence), leaf_angle_deg, percent_open, gate_state, engine, latency_ms),
        )

    def record_crossing(
        self,
        ts: float,
        direction: str,
        kind: str = "vehicle",
        lane: str | None = None,
        confidence: float = 1.0,
    ):
        """Persists a vehicle, pedestrian, or bicycle crossing."""
        self.conn.execute(
            "INSERT INTO vehicle_crossings (ts, iso, direction, lane, kind, confidence) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (ts, to_iso(ts), direction, lane, kind, float(confidence)),
        )

    def record_boat(
        self,
        ts: float,
        direction: str,
        opening_id: int | None = None,
        confidence: float = 1.0,
    ):
        """Persists a marine channel passage."""
        self.conn.execute(
            "INSERT INTO boat_passages (ts, iso, direction, opening_id, confidence) "
            "VALUES (?, ?, ?, ?, ?)",
            (ts, to_iso(ts), direction, opening_id, float(confidence)),
        )

    def record_milestone(
        self,
        ts: float,
        kind: str,
        source: str = "detector",
        confidence: float = 1.0,
        validated: int = 0,
        opening_id: int | None = None,
    ):
        """Persists a physical event milestone (e.g. road_blocked, lift_start)."""
        self.conn.execute(
            "INSERT OR REPLACE INTO road_milestones (ts, iso, kind, source, confidence, validated, opening_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ts, to_iso(ts), kind, source, float(confidence), validated, opening_id),
        )

    def upsert_opening(self, op: dict[str, Any]) -> int:
        """Upserts an opening event record."""
        cols = [
            "lift_start", "full_open_at", "lower_start", "seated",
            "rise_s", "hold_s", "lower_s", "total_s", "complete",
            "max_openness", "schedule_offset_s", "scheduled", "regime",
            "boats_in", "boats_out", "pre_opening_wait_s", "road_closure_s",
            "clearance_lag_s", "grade_json", "notes"
        ]
        vals = [op.get(c) for c in cols]
        if isinstance(vals[cols.index("grade_json")], dict):
            vals[cols.index("grade_json")] = json.dumps(vals[cols.index("grade_json")])

        placeholders = ", ".join("?" for _ in cols)
        update_clause = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "lift_start")

        with self.conn:
            self.conn.execute(
                f"INSERT INTO openings ({', '.join(cols)}) VALUES ({placeholders}) "
                f"ON CONFLICT(lift_start) DO UPDATE SET {update_clause}",
                vals,
            )
            row = self.conn.execute("SELECT id FROM openings WHERE lift_start=?", (op["lift_start"],)).fetchone()
            return row["id"] if row else -1

    def record_health(self, kind: str, detail: str = "", ts: float | None = None):
        """Records system heartbeat or health alert."""
        t = ts or time.time()
        self.conn.execute("INSERT OR REPLACE INTO health VALUES (?, ?, ?, ?)", (t, to_iso(t), kind, detail))

    def get_available_dates(self) -> list[str]:
        """Returns sorted list of distinct calendar dates (YYYY-MM-DD) present in the database."""
        rows = self.conn.execute(
            "SELECT DISTINCT substr(iso, 1, 10) as d FROM readings "
            "UNION "
            "SELECT DISTINCT substr(iso, 1, 10) as d FROM vehicle_crossings "
            "WHERE d IS NOT NULL ORDER BY d DESC"
        ).fetchall()
        return [r["d"] for r in rows if r["d"]]

    def get_hourly_traffic(self, day_start_ts: float, day_end_ts: float) -> list[dict[str, Any]]:
        """Computes 24 hourly buckets of vehicle, pedestrian, bicycle, and boat traffic for a calendar day."""
        day_dt = dt.datetime.fromtimestamp(day_start_ts, LOCAL_TZ)
        tz_offset_hours = int((day_dt.utcoffset() or dt.timedelta()).total_seconds() // 3600)
        tz_mod = f"{tz_offset_hours:+d} hours"

        buckets = [
            {
                "hour": h,
                "vehicles": {"northbound": 0, "southbound": 0},
                "pedestrians": 0,
                "bicycles": 0,
                "boats": {"inbound": 0, "outbound": 0},
            }
            for h in range(24)
        ]

        veh_rows = self.conn.execute(
            f"""
            SELECT
                CAST(strftime('%H', ts, 'unixepoch', '{tz_mod}') AS INTEGER) as hr,
                kind,
                direction,
                COUNT(*) as cnt
            FROM vehicle_crossings
            WHERE ts >= ? AND ts <= ?
            GROUP BY hr, kind, direction
            """,
            (day_start_ts, day_end_ts),
        ).fetchall()

        for r in veh_rows:
            hr, kind, dirn, cnt = r["hr"], r["kind"], r["direction"], r["cnt"]
            if 0 <= hr < 24:
                if kind == "vehicle":
                    if dirn in ("northbound", "southbound"):
                        buckets[hr]["vehicles"][dirn] += cnt
                elif kind == "pedestrian":
                    buckets[hr]["pedestrians"] += cnt
                elif kind == "bicycle":
                    buckets[hr]["bicycles"] += cnt

        boat_rows = self.conn.execute(
            f"""
            SELECT
                CAST(strftime('%H', ts, 'unixepoch', '{tz_mod}') AS INTEGER) as hr,
                direction,
                COUNT(*) as cnt
            FROM boat_passages
            WHERE ts >= ? AND ts <= ?
            GROUP BY hr, direction
            """,
            (day_start_ts, day_end_ts),
        ).fetchall()

        for r in boat_rows:
            hr, dirn, cnt = r["hr"], r["direction"], r["cnt"]
            if 0 <= hr < 24 and dirn in ("inbound", "outbound"):
                buckets[hr]["boats"][dirn] += cnt

        return buckets

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass
