import tempfile
import unittest
from pathlib import Path
from app.capture import CycleCaptureBuffer
from app.config import Config

class TestCaptureBuffer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Config(
            capture_dir=Path(self.tmp.name),
            pre_event_buffer_seconds=5,
            camera_fps=10,
            capture_max_cycles=3,
            capture_max_mb=10,
        )
        self.buf = CycleCaptureBuffer(self.cfg)

    def tearDown(self):
        self.tmp.cleanup()

    def test_ring_buffer_and_cycle_recording(self):
        # Add 10 dummy frames
        for i in range(10):
            self.buf.append(1000.0 + i * 0.1, b"\xff\xd8\xff\xd9")

        self.assertEqual(len(self.buf.ring_buffer), 10)

        # Start recording
        self.buf.start_recording("test_cycle_01", 1001.0)
        self.buf.append(1002.0, b"\xff\xd8\xff\xd9")
        self.buf.stop_recording(metadata={"test": True})

        event_dir = self.cfg.capture_dir / "events" / "test_cycle_01"
        self.assertTrue(event_dir.is_dir())
        manifest = event_dir / "manifest.json"
        self.assertTrue(manifest.is_file())

if __name__ == "__main__":
    unittest.main()
