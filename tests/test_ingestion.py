import unittest
from app.config import Config
from app.ingestion import MockStreamReader, AuthenticationError

class TestIngestion(unittest.TestCase):
    def test_mock_stream_reader(self):
        cfg = Config(camera_fps=20, camera_width=640, camera_height=360)
        reader = MockStreamReader(cfg, fps=30.0)
        frames = []
        for ts, fb in reader.frames(max_frames=3):
            frames.append((ts, fb))
            self.assertTrue(len(fb) > 0)
            self.assertTrue(fb.startswith(b"\xff\xd8"))
            self.assertTrue(fb.endswith(b"\xff\xd9"))
        self.assertEqual(len(frames), 3)

    def test_authentication_error_type(self):
        err = AuthenticationError("Unauthorized")
        self.assertIsInstance(err, RuntimeError)

if __name__ == "__main__":
    unittest.main()
