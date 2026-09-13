"""
Charlevoix Memorial Bridge - Vercel Edge Serverless App.

Serves the Web Dashboard, Visual Auditor, and Edge Telemetry Proxy.
The primary high-speed GPU vision pipeline and camera ingestion run on the
dedicated NVIDIA Spark host (spark-2079).
"""
import os
from pathlib import Path
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
import httpx

app = FastAPI(title="Charlevoix Memorial Bridge Platform", version="2.0.0")

ROOT_DIR = Path(__file__).resolve().parent.parent
STATS_ORIGIN = os.getenv("STATS_ORIGIN", "http://127.0.0.1:8090").rstrip("/")


@app.get("/")
async def root():
    index_path = ROOT_DIR / "index.html"
    if index_path.is_file():
        return FileResponse(index_path, media_type="text/html")
    return JSONResponse({"status": "ok", "service": "charlevoix-bridge-status-v2"})


@app.get("/audit")
async def audit_page():
    audit_path = ROOT_DIR / "audit" / "index.html"
    if audit_path.is_file():
        return FileResponse(audit_path, media_type="text/html")
    return JSONResponse({"error": "Audit page not found"}, status_code=404)


@app.get("/styles.css")
async def styles():
    css_path = ROOT_DIR / "styles.css"
    if css_path.is_file():
        return FileResponse(css_path, media_type="text/css")
    return Response(status_code=404)


@app.get("/app.js")
async def main_js():
    js_path = ROOT_DIR / "app.js"
    if js_path.is_file():
        return FileResponse(js_path, media_type="application/javascript")
    return Response(status_code=404)


@app.get("/audit/audit.js")
async def audit_js():
    js_path = ROOT_DIR / "audit" / "audit.js"
    if js_path.is_file():
        return FileResponse(js_path, media_type="application/javascript")
    return Response(status_code=404)


@app.get("/api/stats")
async def proxy_stats(request: Request):
    query_str = request.url.query
    target_url = f"{STATS_ORIGIN}/stats"
    if query_str:
        target_url = f"{target_url}?{query_str}"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(target_url, headers={"Accept": "application/json"})
            data = resp.json()
            headers = {}
            if data.get("is_historical"):
                headers["Cache-Control"] = "public, max-age=3600, s-maxage=86400"
            else:
                headers["Cache-Control"] = "no-store, max-age=0"
            return JSONResponse(content=data, status_code=resp.status_code, headers=headers)
    except Exception:
        return JSONResponse(
            {"error": "Bridge telemetry temporarily unavailable"},
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )


@app.get("/api/live")
async def proxy_live():
    target_url = f"{STATS_ORIGIN}/live.jpg"
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(target_url)
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                media_type=resp.headers.get("content-type", "image/jpeg"),
                headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
            )
    except Exception:
        return JSONResponse(
            {"error": "Live camera stream temporarily unavailable"},
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )


@app.api_route("/api/captures", methods=["GET", "POST"])
async def proxy_captures(request: Request):
    action = request.query_params.get("action")
    target = "/captures"
    if action == "recognize":
        target = "/recognize"
    target_url = f"{STATS_ORIGIN}{target}"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"
    try:
        body = await request.body()
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.request(
                request.method,
                target_url,
                content=body if request.method == "POST" else None,
                headers={"Content-Type": request.headers.get("content-type", "application/json")},
            )
            content_type = resp.headers.get("content-type", "")
            if "image/" in content_type:
                return Response(
                    content=resp.content,
                    status_code=resp.status_code,
                    media_type=content_type,
                    headers={"Cache-Control": "public, max-age=86400, immutable"},
                )
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                media_type=content_type,
                headers={"Cache-Control": "no-store, max-age=0"},
            )
    except Exception:
        return JSONResponse(
            {"error": "Captures service temporarily unavailable"},
            status_code=503,
            headers={"Cache-Control": "no-store"},
        )
