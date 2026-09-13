import tempfile
import unittest
from pathlib import Path
from app.api import APIDaemon
from app.config import Config

class TestAPIEndpoints(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Config(
            db_path=Path(self.tmp.name) / "test.db",
            capture_dir=Path(self.tmp.name) / "captures",
            live_image_path=Path(self.tmp.name) / "live.jpg",
        )
        self.daemon = APIDaemon(self.cfg)

    def tearDown(self):
        self.daemon.store.close()
        self.tmp.cleanup()

    def test_get_stats_empty(self):
        stats = self.daemon.get_stats()
        self.assertIn("state", stats)
        self.assertIn("windows", stats)
        self.assertIn("schedule_slots", stats)
        self.assertEqual(len(stats["schedule_slots"]), 33)

    def test_recognize_frame_mock(self):
        # Create minimal 10x10 JPEG
        import io
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (100, 100), color="blue").save(buf, format="JPEG")
        rec = self.daemon.recognize_frame(buf.getvalue())
        self.assertTrue(rec["ok"])
        self.assertEqual(rec["width"], 100)
        self.assertIn("counts", rec)
        self.assertIn("infrastructure", rec)

if __name__ == "__main__":
    unittest.main()
