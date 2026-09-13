"""
Vercel Deployment Compatibility Shim.

Exports 'app', 'application', and 'handler' to satisfy Vercel's automatic
framework detection when the repository is imported under FastAPI/Python presets.
The primary computer vision engine and analytics pipeline runs on the
dedicated NVIDIA Spark appliance (spark-2079).
"""
from http.server import BaseHTTPRequestHandler
import json


class ASGIApp:
    """Standard ASGI 3.0 application callable."""

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            body = json.dumps({
                "status": "ok",
                "service": "charlevoix-bridge-status-v2",
                "message": "Charlevoix Memorial Bridge Platform",
            }).encode("utf-8")
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"cache-control", b"public, max-age=60"),
                ],
            })
            await send({
                "type": "http.response.body",
                "body": body,
            })


app = ASGIApp()
application = app


def handler(environ_or_request, start_response=None):
    """WSGI / Serverless handler fallback."""
    if callable(start_response):
        status = "200 OK"
        headers = [
            ("Content-Type", "application/json; charset=utf-8"),
            ("Cache-Control", "public, max-age=60"),
        ]
        start_response(status, headers)
        return [json.dumps({"status": "ok", "service": "charlevoix-bridge-status-v2"}).encode("utf-8")]
    return None
