from __future__ import annotations

import asyncio
import hmac
import os
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import __version__

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_DIR = Path(os.getenv("PVE_FAN_WEB_DATA", "/data"))
DB_PATH = DATA_DIR / "history.sqlite3"
WEB_TOKEN = os.getenv("PVE_FAN_WEB_TOKEN", "").strip()
AGENT_URL = os.getenv("PVE_FAN_AGENT_URL", "http://127.0.0.1:9488").rstrip("/")
AGENT_TOKEN = os.getenv("PVE_FAN_AGENT_TOKEN", "").strip()
POLL_SECONDS = max(2, int(os.getenv("PVE_FAN_HISTORY_INTERVAL", "5")))
RETENTION_HOURS = max(1, int(os.getenv("PVE_FAN_HISTORY_RETENTION_HOURS", "48")))

if not WEB_TOKEN:
    raise RuntimeError("PVE_FAN_WEB_TOKEN is required")
if not AGENT_TOKEN:
    raise RuntimeError("PVE_FAN_AGENT_TOKEN is required")


def db() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS metrics ("
        "ts INTEGER NOT NULL, metric TEXT NOT NULL, source_id TEXT NOT NULL, "
        "label TEXT NOT NULL, value REAL NOT NULL)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_metrics_ts ON metrics(ts)")
    return conn


def store_snapshot(data: dict) -> None:
    now = int(time.time())
    rows = []
    hw = data.get("hardware", {})
    for item in hw.get("temperatures", []):
        rows.append((now, "temperature", item.get("id", ""), item.get("label", ""), float(item.get("celsius", 0))))
    for item in hw.get("fans", []):
        rows.append((now, "fan_rpm", item.get("id", ""), item.get("label", ""), float(item.get("rpm", 0))))
    for item in hw.get("pwms", []):
        rows.append((now, "pwm", item.get("id", ""), item.get("label", ""), float(item.get("percent", 0))))
    with db() as conn:
        conn.executemany("INSERT INTO metrics(ts,metric,source_id,label,value) VALUES(?,?,?,?,?)", rows)
        cutoff = now - RETENTION_HOURS * 3600
        conn.execute("DELETE FROM metrics WHERE ts < ?", (cutoff,))
        conn.commit()


async def agent_get(path: str) -> dict:
    headers = {"Authorization": f"Bearer {AGENT_TOKEN}"}
    async with httpx.AsyncClient(timeout=5) as client:
        response = await client.get(f"{AGENT_URL}{path}", headers=headers)
        response.raise_for_status()
        return response.json()


async def history_loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            data = await agent_get("/api/overview")
            await asyncio.to_thread(store_snapshot, data)
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop.wait(), timeout=POLL_SECONDS)
        except asyncio.TimeoutError:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with db():
        pass
    stop = asyncio.Event()
    task = asyncio.create_task(history_loop(stop))
    yield
    stop.set()
    await task


app = FastAPI(title="PVE Fan Control Web", version=__version__, docs_url=None, redoc_url=None, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def require_web_token(
    authorization: Annotated[str | None, Header()] = None,
    x_pve_fan_token: Annotated[str | None, Header()] = None,
) -> None:
    candidate = x_pve_fan_token
    if authorization and authorization.lower().startswith("bearer "):
        candidate = authorization[7:].strip()
    if not candidate or not hmac.compare_digest(candidate, WEB_TOKEN):
        raise HTTPException(status_code=401, detail="Invalid Web UI token")


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health", dependencies=[Depends(require_web_token)])
def health():
    return {"ok": True, "version": __version__, "role": "web", "agent_url": AGENT_URL}


@app.get("/api/history", dependencies=[Depends(require_web_token)])
def history(
    minutes: int = Query(default=60, ge=5, le=2880),
    metric: str = Query(default="temperature", pattern="^(temperature|fan_rpm|pwm)$"),
):
    cutoff = int(time.time()) - minutes * 60
    with db() as conn:
        rows = conn.execute(
            "SELECT ts, source_id, label, value FROM metrics WHERE ts >= ? AND metric = ? ORDER BY ts ASC",
            (cutoff, metric),
        ).fetchall()
    series: dict[str, dict] = {}
    for ts, source_id, label, value in rows:
        entry = series.setdefault(source_id, {"id": source_id, "label": label, "points": []})
        entry["points"].append([ts, value])
    for entry in series.values():
        points = entry["points"]
        if len(points) > 800:
            step = max(1, len(points) // 800)
            entry["points"] = points[::step]
    return {"metric": metric, "minutes": minutes, "series": list(series.values())}


@app.api_route(
    "/agent/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    dependencies=[Depends(require_web_token)],
)
async def proxy_agent(path: str, request: Request):
    headers = {"Authorization": f"Bearer {AGENT_TOKEN}"}
    body = await request.body()
    query = request.url.query
    url = f"{AGENT_URL}/{path}"
    if query:
        url += "?" + query
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.request(
                request.method,
                url,
                headers={**headers, "Content-Type": request.headers.get("content-type", "application/json")},
                content=body or None,
            )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Agent unavailable: {exc}") from exc
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            payload = response.json()
        except ValueError:
            payload = {"detail": response.text}
        return JSONResponse(payload, status_code=response.status_code)
    return Response(response.content, status_code=response.status_code, media_type=content_type or "text/plain")
