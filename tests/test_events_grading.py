import datetime as dt
import unittest
from engine.config import LOCAL_TZ
from engine.events import calculate_performance_grade, calculate_schedule_offset, get_regime

class TestEventsGrading(unittest.TestCase):
    def test_regime_classification(self):
        # Summer daytime -> restricted
        d1 = dt.datetime(2026, 7, 15, 14, 0, tzinfo=LOCAL_TZ)
        self.assertEqual(get_regime(d1), "restricted")

        # Summer night -> on_signal
        d2 = dt.datetime(2026, 7, 15, 23, 0, tzinfo=LOCAL_TZ)
        self.assertEqual(get_regime(d2), "on_signal")

        # Winter -> advance_notice
        d3 = dt.datetime(2026, 2, 10, 10, 0, tzinfo=LOCAL_TZ)
        self.assertEqual(get_regime(d3), "advance_notice")

    def test_schedule_offset(self):
        # 14:01:00 is 60s after 14:00:00 slot
        d = dt.datetime(2026, 7, 15, 14, 1, 0, tzinfo=LOCAL_TZ)
        offset, is_sched = calculate_schedule_offset(d.timestamp())
        self.assertAlmostEqual(offset, 60.0, delta=1.0)
        self.assertTrue(is_sched)

    def test_performance_grade_high_score(self):
        # High volume convoy, punctual
        d = dt.datetime(2026, 7, 15, 14, 0, 30, tzinfo=LOCAL_TZ)
        op = {
            "lift_start": d.timestamp(),
            "regime": "restricted",
            "boats_in": 5,
            "boats_out": 4,
            "road_closure_s": 240.0,
            "max_openness": 95,
        }
        grade = calculate_performance_grade(op)
        self.assertIn(grade["letter"], ("A+", "A"))
        self.assertGreaterEqual(grade["score"], 93)

    def test_performance_grade_empty_lift_penalty(self):
        # 0 boats, extended closure
        d = dt.datetime(2026, 7, 15, 14, 0, 0, tzinfo=LOCAL_TZ)
        op = {
            "lift_start": d.timestamp(),
            "regime": "restricted",
            "boats_in": 0,
            "boats_out": 0,
            "road_closure_s": 450.0,
            "max_openness": 100,
        }
        grade = calculate_performance_grade(op)
        self.assertIn(grade["letter"], ("D", "F", "C-"))

if __name__ == "__main__":
    unittest.main()
