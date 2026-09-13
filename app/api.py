"""Fast API & Telemetry Daemon running on port 8090."""
from __future__ import annotations

import base64
import datetime as dt
import io
import json
import logging
import re
import socketserver
import time
import urllib.parse
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from PIL import Image

from .config import Config, LOCAL_TZ
from .events import calculate_performance_grade, calculate_schedule_offset, get_regime
from .store import Store
from .vision import InfrastructureStateEstimator, ObjectDetector

log = logging.getLogger("api")


def build_schedule_slots(day_start_ts: float) -> list[dict[str, Any]]:
    """Builds the 33 daytime slots (6:00 AM to 10:00 PM) per 33 CFR § 117.641."""
    slots = []
    day_dt = dt.datetime.fromtimestamp(day_start_ts, LOCAL_TZ)
    # 6:00 AM is 6 * 2 = 12 half-hour intervals, through 10:00 PM (22:00 = 44)
    # Total 33 slots: 6:00, 6:30, ..., 22:00
    for hour in range(6, 23):
        for minute in (0, 30):
            if hour == 22 and minute == 30:
                continue
            slot_dt = day_dt.replace(hour=hour, minute=minute, second=0, microsecond=0)
            slot_ts = slot_dt.timestamp()
            time_str = slot_dt.strftime("%-I:%M %p")
            slots.append({
                "ts": slot_ts,
                "label": time_str,
                "hour": hour,
                "minute": minute,
            })
    return slots


class APIDaemon:
    """Telemetry API service providing endpoints for Web Dashboard, Auditor, and iOS Live Activity."""

    def __init__(self, config: Config):
        self.config = config
        self.store = Store(config.db_path)
        self.detector = ObjectDetector(
            model_path=config.model_path,
            device=config.device,
            mock=False,
        )
        self.state_estimator = InfrastructureStateEstimator(zones=config.zones)

    def get_stats(self, date_str: str | None = None) -> dict[str, Any]:
        """Generates comprehensive real-time or historical telemetry snapshot."""
        now = time.time()
        today_dt = dt.datetime.fromtimestamp(now, LOCAL_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
        today_midnight = today_dt.timestamp()
        today_str = today_dt.strftime("%Y-%m-%d")

        is_historical = False
        if date_str:
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
                raise ValueError(f"Invalid date format: {date_str}. Expected YYYY-MM-DD")
            target_dt = dt.datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=LOCAL_TZ)
            day_start = target_dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            day_end = day_start + 86400.0
            is_historical = (day_start < today_midnight)
            selected_date = date_str
        else:
            day_start = today_midnight
            day_end = now
            selected_date = today_str

        # 1. Fetch latest physical reading
        latest_reading = self.store.conn.execute(
            "SELECT * FROM readings ORDER BY ts DESC LIMIT 1"
        ).fetchone()

        bridge_state = "closed" if is_historical else (latest_reading["state"] if latest_reading else "unknown")
        gate_state = "raised" if is_historical else (latest_reading["gate_state"] if latest_reading else "unknown")
        pct_open = 0 if is_historical else (latest_reading["percent_open"] if latest_reading else 0)
        last_ts = latest_reading["ts"] if latest_reading else None
        last_iso = latest_reading["iso"] if latest_reading else None

        freshness_age = (now - last_ts) if (last_ts and not is_historical) else None
        is_fresh = (freshness_age is not None and freshness_age < 15.0)

        # 2. Crossing metrics for today / selected date
        q_start = day_start
        q_end = day_end if is_historical else now

        veh_rows = self.store.conn.execute(
            "SELECT direction, count(*) as cnt FROM vehicle_crossings "
            "WHERE kind='vehicle' AND ts >= ? AND ts <= ? GROUP BY direction",
            (q_start, q_end),
        ).fetchall()
        veh_counts = {r["direction"]: r["cnt"] for r in veh_rows}

        boat_rows = self.store.conn.execute(
            "SELECT direction, count(*) as cnt FROM boat_passages "
            "WHERE ts >= ? AND ts <= ? GROUP BY direction",
            (q_start, q_end),
        ).fetchall()
        boat_counts = {r["direction"]: r["cnt"] for r in boat_rows}

        people_rows = self.store.conn.execute(
            "SELECT kind, count(*) as cnt FROM vehicle_crossings "
            "WHERE kind IN ('pedestrian', 'bicycle') AND ts >= ? AND ts <= ? GROUP BY kind",
            (q_start, q_end),
        ).fetchall()
        people_counts = {r["kind"]: r["cnt"] for r in people_rows}

        windows = {
            "today": {
                "start": q_start,
                "end": q_end,
                "vehicles": {
                    "northbound": veh_counts.get("northbound", 0),
                    "southbound": veh_counts.get("southbound", 0),
                },
                "boats": {
                    "inbound": boat_counts.get("inbound", 0),
                    "outbound": boat_counts.get("outbound", 0),
                },
                "pedestrians": people_counts.get("pedestrian", 0),
                "bicycles": people_counts.get("bicycle", 0),
            }
        }

        # 3. 24-Hour hourly traffic distribution
        hourly_traffic = self.store.get_hourly_traffic(day_start, day_end)

        # 4. Openings for the selected date
        op_rows = self.store.conn.execute(
            "SELECT * FROM openings WHERE lift_start >= ? AND lift_start <= ? ORDER BY lift_start ASC",
            (q_start, q_end),
        ).fetchall()

        openings_list = []
        for r in op_rows:
            op_dict = dict(r)
            if op_dict.get("grade_json"):
                try:
                    op_dict["grade"] = json.loads(op_dict["grade_json"])
                except (ValueError, TypeError):
                    op_dict["grade"] = calculate_performance_grade(op_dict)
            else:
                op_dict["grade"] = calculate_performance_grade(op_dict)
            openings_list.append(op_dict)

        # 5. Build 33-slot schedule grid
        schedule_slots = build_schedule_slots(day_start)
        scheduled_openings = []
        off_schedule_openings = []

        for op in openings_list:
            if op.get("scheduled"):
                scheduled_openings.append(op)
            else:
                off_schedule_openings.append(op)

        # Slot matching
        for slot in schedule_slots:
            s_ts = slot["ts"]
            matched_op = next(
                (op for op in scheduled_openings if abs(op["lift_start"] - s_ts) <= 300.0),
                None,
            )
            if matched_op:
                slot["status"] = "opened"
                slot["opening"] = matched_op
            elif not is_historical and abs(now - s_ts) <= 180.0:
                slot["status"] = "in_window"
            elif not is_historical and now < s_ts:
                slot["status"] = "upcoming"
            else:
                slot["status"] = "uncalled"

        # 6. Marine traffic summary
        total_boats = boat_counts.get("inbound", 0) + boat_counts.get("outbound", 0)
        opening_boats = sum((op.get("boats_in", 0) + op.get("boats_out", 0)) for op in openings_list)
        marine_summary = {
            "total": total_boats,
            "inbound": boat_counts.get("inbound", 0),
            "outbound": boat_counts.get("outbound", 0),
            "during_openings": opening_boats,
            "under_closed_span": max(0, total_boats - opening_boats),
        }

        # 7. Recent crossings
        recent_crossings = self.store.conn.execute(
            "SELECT ts, iso, direction, kind FROM vehicle_crossings "
            "WHERE ts >= ? ORDER BY ts DESC LIMIT 15",
            (q_start,),
        ).fetchall()
        recent = [dict(rx) for rx in recent_crossings]

        return {
            "generated_at": now,
            "selected_date": selected_date,
            "is_historical": is_historical,
            "available_dates": self.store.get_available_dates(),
            "state": bridge_state,
            "gate_state": gate_state,
            "percent_open": pct_open,
            "last_updated": last_iso,
            "fresh": is_fresh,
            "windows": windows,
            "marine": marine_summary,
            "hourly_traffic": hourly_traffic,
            "openings": openings_list,
            "schedule_slots": schedule_slots,
            "off_schedule_openings": off_schedule_openings,
            "recent": recent,
        }

    def recognize_frame(self, frame_bytes: bytes) -> dict[str, Any]:
        """Runs on-demand single-frame recognition for Auditor HUD inspection (hotkey R)."""
        t0 = time.perf_counter()
        img = Image.open(io.BytesIO(frame_bytes)).convert("RGB")
        w, h = img.size

        # 1. Detect objects
        detections = self.detector.detect(img)

        # 2. Classify zones
        zones = self.config.zones
        objects = []
        counts = {"vehicle": 0, "vessel": 0, "pedestrian": 0, "bicycle": 0}

        for d in detections:
            nx = d.cx / max(1.0, w)
            ny = d.cy / max(1.0, h)
            zone = "other"
            if zones.channel_norm[0] <= nx <= zones.channel_norm[2] and zones.channel_norm[1] <= ny <= zones.channel_norm[3]:
                zone = "channel"
            elif zones.roadway_norm[0] <= nx <= zones.roadway_norm[2] and zones.roadway_norm[1] <= ny <= zones.roadway_norm[3]:
                zone = "roadway"
            elif zones.walk_far_norm[0] <= nx <= zones.walk_far_norm[2] and zones.walk_far_norm[1] <= ny <= zones.walk_far_norm[3]:
                zone = "walk_far"
            elif zones.walk_near_norm[0] <= nx <= zones.walk_near_norm[2] and zones.walk_near_norm[1] <= ny <= zones.walk_near_norm[3]:
                zone = "walk_near"

            if d.kind in counts:
                counts[d.kind] += 1

            objects.append({
                "kind": d.kind,
                "score": round(d.score, 3),
                "box": [round(c, 1) for c in d.box],
                "cx": round(d.cx, 1),
                "cy": round(d.cy, 1),
                "zone": zone,
            })

        # 3. Estimate infrastructure state
        infra = self.state_estimator.estimate(detections)
        latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)

        return {
            "ok": True,
            "width": w,
            "height": h,
            "latency_ms": latency_ms,
            "counts": counts,
            "objects": objects,
            "infrastructure": {
                "leaf_state": infra.leaf_state,
                "leaf_angle_deg": infra.leaf_angle_deg,
                "percent_open": infra.percent_open,
                "gate_state": infra.gate_state,
                "confidence": infra.confidence,
            },
        }

    def get_captures_list(self) -> list[dict[str, Any]]:
        """Returns list of recorded opening cycles and audit statuses."""
        events_dir = self.config.capture_dir / "events"
        if not events_dir.is_dir():
            return []

        results = []
        for edir in sorted(events_dir.iterdir(), reverse=True):
            if not edir.is_dir() or edir.name.startswith("."):
                continue

            manifest_file = edir / "manifest.json"
            audit_file = edir / "audit.json"

            manifest = {}
            if manifest_file.exists():
                try:
                    manifest = json.loads(manifest_file.read_text())
                except Exception:
                    pass

            audit_info = None
            if audit_file.exists():
                try:
                    audit_info = json.loads(audit_file.read_text())
                except Exception:
                    pass

            jpg_count = len(list(edir.glob("*.jpg")))
            results.append({
                "id": edir.name,
                "start_ts": manifest.get("start_ts"),
                "end_ts": manifest.get("end_ts"),
                "duration_s": manifest.get("duration_s"),
                "frames_count": manifest.get("frames_count", jpg_count),
                "has_audit": audit_info is not None,
                "audit_certified_at": audit_info.get("certified_at") if audit_info else None,
                "audit_milestones": audit_info.get("milestones") if audit_info else None,
            })
        return results

    def get_capture_details(self, event_id: str) -> dict[str, Any] | None:
        """Returns detailed capture manifest and frame index."""
        clean_id = re.sub(r"[^a-zA-Z0-9_-]", "", event_id)
        edir = self.config.capture_dir / "events" / clean_id
        if not edir.is_dir():
            return None

        manifest_file = edir / "manifest.json"
        audit_file = edir / "audit.json"

        manifest = {}
        if manifest_file.exists():
            try:
                manifest = json.loads(manifest_file.read_text())
            except Exception:
                pass

        audit_data = None
        if audit_file.exists():
            try:
                audit_data = json.loads(audit_file.read_text())
            except Exception:
                pass

        jpgs = sorted(edir.glob("*.jpg"), key=lambda p: float(p.stem) if p.stem.replace(".", "", 1).isdigit() else p.name)
        frames = []
        for p in jpgs:
            try:
                ts = float(p.stem)
            except ValueError:
                ts = p.stat().st_mtime
            frames.append({
                "ts": ts,
                "name": p.name,
                "src": f"/api/captures?id={clean_id}&frame={p.name}",
            })

        return {
            "event_id": clean_id,
            "start_ts": manifest.get("start_ts"),
            "end_ts": manifest.get("end_ts"),
            "duration_s": manifest.get("duration_s"),
            "frames": frames,
            "audit": audit_data,
        }

    def save_audit(self, event_id: str, audit_payload: dict[str, Any]) -> dict[str, Any]:
        """Saves certified human audit to capture directory and persists verified milestones."""
        clean_id = re.sub(r"[^a-zA-Z0-9_-]", "", event_id)
        edir = self.config.capture_dir / "events" / clean_id
        if not edir.is_dir():
            raise FileNotFoundError(f"Event capture {clean_id} not found.")

        certified_at = audit_payload.get("certified_at") or dt.datetime.now(dt.timezone.utc).isoformat()
        audit_record = {
            "schema_version": "2.0",
            "event_id": clean_id,
            "milestones": audit_payload.get("milestones", {}),
            "peak_openness_percent": int(audit_payload.get("peak_openness_percent", 100)),
            "boats": audit_payload.get("boats", {"inbound": 0, "outbound": 0}),
            "conditions": audit_payload.get("conditions", {"environment": "daylight"}),
            "reviewer_notes": str(audit_payload.get("reviewer_notes", "")),
            "certified_at": certified_at,
        }

        # 1. Write audit.json
        (edir / "audit.json").write_text(json.dumps(audit_record, indent=2))

        # 2. Persist verified milestones in SQLite
        milestones = audit_record.get("milestones", {})
        for kind, ts in milestones.items():
            if ts is not None and isinstance(ts, (int, float)):
                self.store.record_milestone(
                    ts=float(ts),
                    kind=str(kind),
                    source="human_audit",
                    confidence=1.0,
                    validated=1,
                )

        return audit_record


class ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True


def make_request_handler(daemon: APIDaemon):
    class RequestHandler(BaseHTTPRequestHandler):
        def do_HEAD(self):
            self._handle_get(is_head=True)

        def do_GET(self):
            self._handle_get(is_head=False)

        def _handle_get(self, is_head: bool = False):
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path.rstrip("/")
            query = urllib.parse.parse_qs(parsed.query)

            # CORS headers
            cors_headers = {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
            }

            # 1. /stats or /api/stats
            if path in ("/stats", "/api/stats"):
                date_param = query.get("date", [None])[0]
                try:
                    stats_data = daemon.get_stats(date_param)
                    body = json.dumps(stats_data).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    for k, v in cors_headers.items():
                        self.send_header(k, v)
                    if stats_data.get("is_historical"):
                        self.send_header("Cache-Control", "public, max-age=86400")
                    else:
                        self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    if not is_head:
                        self.wfile.write(body)
                    return
                except ValueError as e:
                    self._send_error(400, str(e), cors_headers)
                    return
                except Exception as e:
                    log.exception("Error generating stats: %s", e)
                    self._send_error(500, "Stats error", cors_headers)
                    return

            # 2. /live or /api/live (Sub-second low-latency raw camera frame)
            if path in ("/live", "/live.jpg", "/api/live"):
                live_file = daemon.config.live_image_path
                if not live_file.exists():
                    self._send_error(404, "Live camera frame not ready", cors_headers)
                    return
                try:
                    img_data = live_file.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    for k, v in cors_headers.items():
                        self.send_header(k, v)
                    self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                    self.send_header("Content-Length", str(len(img_data)))
                    self.end_headers()
                    if not is_head:
                        self.wfile.write(img_data)
                    return
                except OSError:
                    self._send_error(500, "Error reading live frame", cors_headers)
                    return

            # 3. /captures or /api/captures
            if path in ("/captures", "/api/captures"):
                ev_id = query.get("id", [None])[0]
                frame_name = query.get("frame", [None])[0]

                if ev_id and frame_name:
                    clean_id = re.sub(r"[^a-zA-Z0-9_-]", "", ev_id)
                    clean_frame = re.sub(r"[^a-zA-Z0-9_.-]", "", frame_name)
                    frame_path = daemon.config.capture_dir / "events" / clean_id / clean_frame
                    if not frame_path.is_file():
                        self._send_error(404, "Frame not found", cors_headers)
                        return
                    img_bytes = frame_path.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    for k, v in cors_headers.items():
                        self.send_header(k, v)
                    self.send_header("Cache-Control", "public, max-age=86400, immutable")
                    self.send_header("Content-Length", str(len(img_bytes)))
                    self.end_headers()
                    if not is_head:
                        self.wfile.write(img_bytes)
                    return

                if ev_id:
                    details = daemon.get_capture_details(ev_id)
                    if details is None:
                        self._send_error(404, "Capture not found", cors_headers)
                        return
                    body = json.dumps(details).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    for k, v in cors_headers.items():
                        self.send_header(k, v)
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    if not is_head:
                        self.wfile.write(body)
                    return

                # List all captures
                captures_list = daemon.get_captures_list()
                body = json.dumps(captures_list).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                for k, v in cors_headers.items():
                    self.send_header(k, v)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if not is_head:
                    self.wfile.write(body)
                return

            # 4. Static web assets fallback
            web_dir = (Path(__file__).resolve().parent.parent / "web").resolve()
            rel_path = path.lstrip("/")
            if not rel_path:
                target_file = web_dir / "index.html"
            elif rel_path == "audit":
                target_file = web_dir / "audit" / "index.html"
            else:
                target_file = (web_dir / rel_path).resolve()

            if target_file.is_file() and target_file.is_relative_to(web_dir):
                content_type = "text/plain"
                if target_file.suffix == ".html":
                    content_type = "text/html; charset=utf-8"
                elif target_file.suffix == ".css":
                    content_type = "text/css; charset=utf-8"
                elif target_file.suffix == ".js":
                    content_type = "application/javascript; charset=utf-8"
                elif target_file.suffix == ".json":
                    content_type = "application/json"
                elif target_file.suffix in (".jpg", ".jpeg"):
                    content_type = "image/jpeg"
                elif target_file.suffix == ".png":
                    content_type = "image/png"
                elif target_file.suffix == ".svg":
                    content_type = "image/svg+xml"

                try:
                    data = target_file.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", content_type)
                    for k, v in cors_headers.items():
                        self.send_header(k, v)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    if not is_head:
                        self.wfile.write(data)
                    return
                except OSError:
                    pass

            self._send_error(404, "Not Found", cors_headers)

        def do_POST(self):
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path.rstrip("/")
            query = urllib.parse.parse_qs(parsed.query)

            cors_headers = {
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type",
            }

            content_len = int(self.headers.get("Content-Length", 0))
            if content_len <= 0 or content_len > 15_000_000:
                self._send_error(400, "Invalid payload size", cors_headers)
                return

            raw_body = self.rfile.read(content_len)
            try:
                data = json.loads(raw_body)
            except Exception:
                self._send_error(400, "Malformed JSON", cors_headers)
                return

            # 1. /recognize or /api/recognize (Single-frame HUD inspector)
            if path in ("/recognize", "/api/recognize"):
                img_bytes = None
                if "image_base64" in data:
                    b64 = data["image_base64"]
                    if "," in b64:
                        b64 = b64.split(",", 1)[1]
                    img_bytes = base64.b64decode(b64)
                elif "event_id" in data and "frame" in data:
                    clean_id = re.sub(r"[^a-zA-Z0-9_-]", "", data["event_id"])
                    clean_frame = re.sub(r"[^a-zA-Z0-9_.-]", "", data["frame"])
                    fpath = daemon.config.capture_dir / "events" / clean_id / clean_frame
                    if fpath.is_file():
                        img_bytes = fpath.read_bytes()

                if not img_bytes:
                    self._send_error(400, "Missing image data", cors_headers)
                    return

                result = daemon.recognize_frame(img_bytes)
                body = json.dumps(result).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                for k, v in cors_headers.items():
                    self.send_header(k, v)
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            # 2. /api/audit or /captures/<id>/audit
            if path == "/api/audit" or (path.startswith("/captures/") and path.endswith("/audit")):
                event_id = query.get("id", [None])[0]
                if not event_id:
                    parts = [p for p in path.split("/") if p]
                    if len(parts) >= 2:
                        event_id = parts[1]
                if not event_id:
                    event_id = data.get("event_id")

                if not event_id:
                    self._send_error(400, "Missing event_id", cors_headers)
                    return

                try:
                    audit_record = daemon.save_audit(event_id, data)
                    res = {"ok": True, "audit": audit_record}
                    body = json.dumps(res).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    for k, v in cors_headers.items():
                        self.send_header(k, v)
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                except FileNotFoundError as e:
                    self._send_error(404, str(e), cors_headers)
                    return
                except Exception as e:
                    log.exception("Audit save error: %s", e)
                    self._send_error(500, "Error saving audit", cors_headers)
                    return

            self._send_error(404, "Not Found", cors_headers)

        def do_OPTIONS(self):
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def _send_error(self, code: int, message: str, headers: dict):
            body = json.dumps({"error": message, "code": code}).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            # Suppress default request logging to keep output clean
            pass

    return RequestHandler


def run_api_daemon(config: Config):
    """Starts the Fast API daemon."""
    daemon = APIDaemon(config)
    handler = make_request_handler(daemon)
    server = ThreadedHTTPServer((config.app_host, config.app_port), handler)
    log.info("Fast API Daemon listening on http://%s:%d", config.app_host, config.app_port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        log.info("API daemon stopped.")
