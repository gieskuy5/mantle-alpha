"""
FastAPI dashboard for Mantle Alpha.

Provides a web interface for viewing whale activity, DEX swaps,
AI-generated signals, and anomaly reports.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import settings

logger = logging.getLogger(__name__)

# ── Paths ───────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

# Ensure directories exist
STATIC_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

# ── App ─────────────────────────────────────────────────────
app = FastAPI(
    title="Mantle Alpha Dashboard",
    description="AI-powered smart money tracker on Mantle Network",
    version="0.1.0",
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# ── In-memory data store (replace with DB later) ────────────
_data_store: dict = {
    "whale_events": [],
    "dex_swaps": [],
    "anomaly_reports": [],
    "signals": [],
}


# ── Routes ──────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Render the main dashboard page."""
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "whale_events": _data_store["whale_events"][-20:],
            "signals": _data_store["signals"][-10:],
            "anomaly_reports": _data_store["anomaly_reports"][-5:],
            "dex_swaps": _data_store["dex_swaps"][-20:],
        },
    )


@app.get("/api/health")
async def health() -> dict:
    """Health check endpoint."""
    return {"status": "ok", "service": "mantle-alpha"}


@app.get("/api/whale-events")
async def get_whale_events(limit: int = 50) -> dict:
    """Return recent whale events as JSON."""
    return {"events": _data_store["whale_events"][-limit:]}


@app.get("/api/dex-swaps")
async def get_dex_swaps(limit: int = 50) -> dict:
    """Return recent DEX swap events as JSON."""
    return {"swaps": _data_store["dex_swaps"][-limit:]}


@app.get("/api/signals")
async def get_signals(limit: int = 20) -> dict:
    """Return recent AI-generated trading signals."""
    return {"signals": _data_store["signals"][-limit:]}


@app.get("/api/anomalies")
async def get_anomalies(limit: int = 10) -> dict:
    """Return recent anomaly detection reports."""
    return {"reports": _data_store["anomaly_reports"][-limit:]}


@app.post("/api/whale-events")
async def add_whale_event(request: Request) -> dict:
    """Ingest a new whale event."""
    data = await request.json()
    _data_store["whale_events"].append(data)
    return {"status": "ok"}


@app.post("/api/signals")
async def add_signal(request: Request) -> dict:
    """Ingest a new trading signal."""
    data = await request.json()
    _data_store["signals"].append(data)
    return {"status": "ok"}


# ── Entrypoint ──────────────────────────────────────────────

def start_server() -> None:
    """Start the dashboard server."""
    import uvicorn

    logger.info(
        "Starting Mantle Alpha dashboard on %s:%d",
        settings.dashboard_host,
        settings.dashboard_port,
    )
    uvicorn.run(
        "dashboard.app:app",
        host=settings.dashboard_host,
        port=settings.dashboard_port,
        reload=True,
    )
