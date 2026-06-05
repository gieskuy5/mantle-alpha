"""
FastAPI dashboard for MantleAlpha.

Provides a web interface for viewing whale activity, DEX swaps,
AI-generated signals, and anomaly reports.
"""

from __future__ import annotations

import time
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from config import settings
from dashboard.data_store import data_store as _data_store, get_stats as _get_indexer_stats

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
    title="MantleAlpha Dashboard",
    description="AI-powered smart money tracker on Mantle Network",
    version="0.3.0",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


# ── Routes ──────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Render the main dashboard page."""
    return templates.TemplateResponse(request, "index.html")


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "service": "mantle-alpha", "version": "0.3.0"}


@app.get("/api/config")
async def get_config() -> dict:
    """Return the current configuration (tracked DEXes, chain info, etc.)."""
    dexes = []
    if settings.merchant_moe_router:
        dexes.append({"name": "Merchant Moe", "color": "cyan", "router": settings.merchant_moe_router})
    if settings.agni_finance_router:
        dexes.append({"name": "Agni Finance", "color": "green", "router": settings.agni_finance_router})
    if settings.fluxion_router:
        dexes.append({"name": "Fluxion", "color": "purple", "router": settings.fluxion_router})
    return {
        "chain": {
            "name": "Mantle Network",
            "chain_id": settings.mantle_chain_id,
            "rpc_url": settings.mantle_rpc_url,
            "explorer": "https://mantlescan.xyz",
        },
        "dexes": dexes,
        "whale_threshold_mnt": settings.whale_threshold_mnt,
        "min_swap_amount_usd": settings.min_swap_amount_usd,
        "poll_interval_sec": settings.poll_interval_sec,
        "ai_model": settings.llm_model,
    }


@app.get("/api/stats")
async def get_stats() -> dict:
    """Summary statistics for the dashboard stats bar."""
    idx = _get_indexer_stats()
    swaps = _data_store.get("dex_swaps", [])
    total_volume = sum(s.get("amount_in", 0) for s in swaps) if swaps else 0
    return {
        "total_whale_events": len(_data_store.get("whale_events", [])),
        "active_signals": len(_data_store.get("signals", [])),
        "anomalies_detected": len(_data_store.get("anomaly_reports", [])),
        "total_swaps": len(swaps),
        "total_volume": total_volume,
        "mnt_price": 0.0,
        "mnt_price_change_24h": 0.0,
        "uptime_seconds": int(time.time() - app.state.start_time) if hasattr(app.state, "start_time") else 0,
        "indexer_blocks_processed": idx.get("blocks_processed", 0),
        "indexer_errors": idx.get("errors", 0),
    }


@app.get("/api/whale-events")
async def get_whale_events(limit: int = 20) -> dict:
    events = sorted(
        _data_store.get("whale_events", []),
        key=lambda x: x.get("timestamp", 0),
        reverse=True,
    )
    return {"events": events[:limit]}


@app.get("/api/dex-swaps")
async def get_dex_swaps(limit: int = 30) -> dict:
    swaps = sorted(
        _data_store.get("dex_swaps", []),
        key=lambda x: x.get("timestamp", 0),
        reverse=True,
    )
    return {"swaps": swaps[:limit]}


@app.get("/api/signals")
async def get_signals(limit: int = 10) -> dict:
    signals = sorted(
        _data_store.get("signals", []),
        key=lambda x: x.get("timestamp", 0),
        reverse=True,
    )
    return {"signals": signals[:limit]}


@app.get("/api/anomalies")
async def get_anomalies(limit: int = 10) -> dict:
    reports = sorted(
        _data_store.get("anomaly_reports", []),
        key=lambda x: x.get("timestamp", 0),
        reverse=True,
    )
    return {"reports": reports[:limit]}


@app.get("/api/protocol-health")
async def get_protocol_health() -> dict:
    """TVL and volume metrics per DEX. Returns empty when no data."""
    return {
        "protocols": [],
        "total_tvl": 0,
        "total_volume_24h": 0,
    }


@app.post("/api/whale-events")
async def add_whale_event(request: Request) -> dict:
    data = await request.json()
    data.setdefault("timestamp", time.time())
    _data_store["whale_events"].append(data)
    return {"status": "ok"}


@app.post("/api/signals")
async def add_signal(request: Request) -> dict:
    data = await request.json()
    data.setdefault("timestamp", time.time())
    _data_store["signals"].append(data)
    return {"status": "ok"}


@app.post("/api/dex-swaps")
async def add_dex_swap(request: Request) -> dict:
    data = await request.json()
    data.setdefault("timestamp", time.time())
    _data_store["dex_swaps"].append(data)
    return {"status": "ok"}


@app.post("/api/anomalies")
async def add_anomaly(request: Request) -> dict:
    data = await request.json()
    data.setdefault("timestamp", time.time())
    _data_store["anomaly_reports"].append(data)
    return {"status": "ok"}


# ── Entrypoint ──────────────────────────────────────────────

@app.on_event("startup")
async def startup_event():
    app.state.start_time = time.time()


def start_server() -> None:
    import uvicorn
    logger.info(
        "Starting MantleAlpha dashboard on %s:%d",
        settings.dashboard_host,
        settings.dashboard_port,
    )
    uvicorn.run(
        "dashboard.app:app",
        host=settings.dashboard_host,
        port=settings.dashboard_port,
        reload=True,
    )
