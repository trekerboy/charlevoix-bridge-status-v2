import tempfile
import unittest
from pathlib import Path
from app.store import Store

class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.store = Store(self.tmp.name)

    def tearDown(self):
        self.store.close()
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_wal_mode_and_readings(self):
        cur = self.store.conn.execute("PRAGMA journal_mode;")
        mode = cur.fetchone()[0]
        self.assertEqual(mode.lower(), "wal")

        self.store.record_reading(
            ts=1789000000.0,
            state="down",
            confidence=0.98,
            leaf_angle_deg=0.0,
            percent_open=0,
            gate_state="raised",
        )
        row = self.store.conn.execute("SELECT * FROM readings WHERE ts=1789000000.0").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["state"], "down")
        self.assertEqual(row["percent_open"], 0)

    def test_crossings_and_hourly_traffic(self):
        t0 = 1789000000.0
        self.store.record_crossing(ts=t0 + 10, direction="northbound", kind="vehicle")
        self.store.record_crossing(ts=t0 + 20, direction="southbound", kind="vehicle")
        self.store.record_crossing(ts=t0 + 30, direction="northbound", kind="pedestrian")
        self.store.record_boat(ts=t0 + 40, direction="inbound")

        hourly = self.store.get_hourly_traffic(t0 - 3600, t0 + 3600)
        self.assertEqual(len(hourly), 24)
        total_veh = sum(h["vehicles"]["northbound"] + h["vehicles"]["southbound"] for h in hourly)
        self.assertEqual(total_veh, 2)
        total_boats = sum(h["boats"]["inbound"] + h["boats"]["outbound"] for h in hourly)
        self.assertEqual(total_boats, 1)

    def test_milestones_and_openings(self):
        self.store.record_milestone(ts=1789000100.0, kind="road_blocked", source="detector")
        self.store.record_milestone(ts=1789000120.0, kind="lift_start", source="detector")

        op_id = self.store.upsert_opening({
            "lift_start": 1789000120.0,
            "full_open_at": 1789000180.0,
            "lower_start": 1789000220.0,
            "seated": 1789000260.0,
            "total_s": 140.0,
            "road_closure_s": 180.0,
            "boats_in": 2,
            "boats_out": 1,
            "notes": "Test lift",
        })
        self.assertGreater(op_id, 0)
        row = self.store.conn.execute("SELECT * FROM openings WHERE id=?", (op_id,)).fetchone()
        self.assertEqual(row["boats_in"], 2)
        self.assertEqual(row["total_s"], 140.0)

if __name__ == "__main__":
    unittest.main()
