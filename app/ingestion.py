"""Resilient HTTP Digest MJPEG stream ingestion client."""
from __future__ import annotations

import io
import logging
import random
import time
import urllib.error
import urllib.request
from typing import Generator, Iterator
from PIL import Image, ImageDraw

from .config import Config

log = logging.getLogger("ingestion")


class AuthenticationError(RuntimeError):
    """Raised when camera returns HTTP 401 Unauthorized to prevent account lockout."""
    pass


class MJPEGStreamReader:
    """Consumes a single multipart/x-mixed-replace MJPEG stream with HTTP Digest Authentication."""

    def __init__(self, config: Config):
        self.config = config
        self.url = config.camera_url
        self.user = config.camera_user
        self.password = config.camera_pass
        self._running = False
        self._consecutive_errors = 0

    def _build_opener(self) -> urllib.request.OpenerDirector:
        """Builds urllib opener with HTTP Digest Authentication handler."""
        password_mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        if self.user and self.password:
            password_mgr.add_password(None, self.url, self.user, self.password)
        handler = urllib.request.HTTPDigestAuthHandler(password_mgr)
        return urllib.request.build_opener(handler)

    def frames(self, max_frames: int | None = None) -> Iterator[tuple[float, bytes]]:
        """Yields (timestamp, jpeg_bytes) from the MJPEG stream with backoff and error recovery."""
        self._running = True
        frame_count = 0

        while self._running:
            opener = self._build_opener()
            req = urllib.request.Request(self.url, headers={"User-Agent": "BridgecamNextEngine/2.0"})
            response = None

            try:
                log.info("Connecting to camera MJPEG stream at host %s...", self.config.camera_host)
                response = opener.open(req, timeout=10.0)
                self._consecutive_errors = 0
                log.info("Connected to MJPEG stream. Starting frame ingestion.")

                buffer = bytearray()
                while self._running:
                    chunk = response.read(16384)
                    if not chunk:
                        raise ConnectionResetError("Stream connection closed by camera")

                    buffer.extend(chunk)

                    # Scan for JPEG start (0xFF 0xD8) and end (0xFF 0xD9)
                    while True:
                        start_idx = buffer.find(b"\xff\xd8")
                        if start_idx == -1:
                            # Keep only tail of buffer to catch split marker
                            if len(buffer) > 2:
                                del buffer[:-2]
                            break

                        end_idx = buffer.find(b"\xff\xd9", start_idx + 2)
                        if end_idx == -1:
                            # Incomplete frame, wait for next chunk
                            if start_idx > 0:
                                del buffer[:start_idx]
                            break

                        frame_bytes = bytes(buffer[start_idx : end_idx + 2])
                        del buffer[: end_idx + 2]
                        ts = time.time()

                        frame_count += 1
                        yield ts, frame_bytes

                        if max_frames and frame_count >= max_frames:
                            self._running = False
                            return

            except urllib.error.HTTPError as e:
                if e.code == 401:
                    log.critical("HTTP 401 Unauthorized received from camera! Halting immediately to prevent lockout.")
                    self._running = False
                    raise AuthenticationError("Camera authentication failed (HTTP 401). Check credentials.") from e
                log.warning("HTTP error from camera stream (code %s): %s", e.code, e)
                self._handle_backoff()

            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
                log.warning("Camera stream connection error: %s", e)
                self._handle_backoff()

            finally:
                if response is not None:
                    try:
                        response.close()
                    except Exception:
                        pass

    def _handle_backoff(self):
        """Exponential backoff with jitter up to 30 seconds."""
        self._consecutive_errors += 1
        delay = min(30.0, (2.0 ** min(self._consecutive_errors, 5)) + random.uniform(0.5, 2.0))
        log.info("Backing off camera connection for %.1f seconds (attempt %d)...", delay, self._consecutive_errors)
        time.sleep(delay)

    def stop(self):
        """Stops stream ingestion."""
        self._running = False


class MockStreamReader:
    """Generates synthetic 1280x720 10 FPS camera frames for testing and offline development."""

    def __init__(self, config: Config, fps: float = 10.0):
        self.config = config
        self.fps = fps
        self._running = True

    def frames(self, max_frames: int | None = None) -> Iterator[tuple[float, bytes]]:
        frame_interval = 1.0 / self.fps
        count = 0
        w, h = self.config.camera_width, self.config.camera_height

        while self._running:
            ts = time.time()
            img = Image.new("RGB", (w, h), color=(35, 45, 55))
            draw = ImageDraw.Draw(img)

            # Draw roadway deck
            draw.rectangle([int(w * 0.20), int(h * 0.44), int(w * 0.65), int(h * 0.56)], fill=(80, 85, 90))
            # Draw channel water
            draw.rectangle([int(w * 0.20), int(h * 0.56), int(w * 0.65), int(h * 0.95)], fill=(30, 70, 95))
            # Text label
            draw.text((20, 20), f"Mock Axis Camera - Native 720p\nFrame {count} - {ts:.3f}", fill=(255, 255, 255))

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            frame_bytes = buf.getvalue()

            count += 1
            yield ts, frame_bytes

            if max_frames and count >= max_frames:
                break

            time.sleep(frame_interval)

    def stop(self):
        self._running = False
