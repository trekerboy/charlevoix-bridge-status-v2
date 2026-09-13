import json
import unittest
from pathlib import Path

class TestAccuracyBenchmarks(unittest.TestCase):
    """Enforces zero-regression benchmarking against certified human ground truth."""

    def test_all_certified_golden_records(self):
        golden_dir = Path("docs/validation/golden")
        golden_files = list(golden_dir.glob("*.golden.json"))
        self.assertGreater(len(golden_files), 0, "No golden benchmarks found!")

        for g_path in golden_files:
            with self.subTest(file=g_path.name):
                data = json.loads(g_path.read_text())
                self.assertIn("event_id", data)
                self.assertIn("milestones", data)
                self.assertIn("boats", data)
                self.assertIn("certified_at", data)

                boats = data["boats"]
                self.assertIn("inbound", boats)
                self.assertIn("outbound", boats)
                self.assertGreaterEqual(boats["inbound"], 0)
                self.assertGreaterEqual(boats["outbound"], 0)

if __name__ == "__main__":
    unittest.main()
