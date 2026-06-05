"""
FastAPI dashboard for MantleAlpha.

Provides a web interface for viewing whale activity, DEX swaps,
AI-generated signals, and anomaly reports.
"""

from __future__ import annotations

import random
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
    version="0.2.0",
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

# ── Seed demo data if empty ────────────────────────────────
def _seed_demo_data():
    """Populate demo data so the dashboard looks alive."""
    now = time.time()
    tokens = ["MNT", "USDC", "USDT", "WETH", "WBTC", "cmETH"]
    dexes = ["Merchant Moe", "Agni Finance", "Fluxion"]
    event_types = ["large_transfer", "dex_buy", "dex_sell", "bridge_in", "bridge_out"]
    signal_actions = ["buy", "sell", "hold"]
    wallets = [
        "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18",
        "0x8Ba1f109551bD432803012645Ac136ddd64DBA72",
        "0xAb5801a7D398351b8bE11C439e05C5B3259aeC9B",
        "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984",
        "0x6B175474E89094C44Da98b954EedeAC495271d0F",
        "0xdAC17F958D2ee523a2206206994597C13D831ec7",
    ]

    for i in range(30):
        ts = now - random.randint(5, 3600)
        _data_store["whale_events"].append({
            "address": random.choice(wallets),
            "event_type": random.choice(event_types),
            "amount_mnt": round(random.uniform(500, 50000), 2),
            "block_number": 7500000 + random.randint(0, 10000),
            "timestamp": ts,
            "token": random.choice(tokens),
        })

    for i in range(40):
        ts = now - random.randint(5, 3600)
        token_in = random.choice(tokens)
        token_out = random.choice([t for t in tokens if t != token_in])
        _data_store["dex_swaps"].append({
            "dex": random.choice(dexes),
            "sender": random.choice(wallets),
            "token_in": token_in,
            "token_out": token_out,
            "amount_in": round(random.uniform(10, 10000), 4),
            "amount_out": round(random.uniform(10, 10000), 4),
            "block_number": 7500000 + random.randint(0, 10000),
            "timestamp": ts,
            "tx_hash": "0x" + "".join(random.choices("0123456789abcdef", k=64)),
        })

    for i in range(8):
        ts = now - random.randint(30, 7200)
        _data_store["signals"].append({
            "token": random.choice(tokens),
            "action": random.choice(signal_actions),
            "confidence": round(random.uniform(0.55, 0.98), 2),
            "reasoning": random.choice([
                "Whale accumulation detected across 3+ wallets over 24h",
                "Large outflow from DEX — potential sell pressure incoming",
                "Smart money rotating into this asset at key support level",
                "Unusual volume spike correlating with bridge activity",
                "Cross-DEX arbitrage opportunity identified by AI model",
                "Institutional wallets showing consistent buy patterns",
            ]),
            "price_target": round(random.uniform(0.5, 5.0), 3),
            "timestamp": ts,
        })

    for i in range(5):
        ts = now - random.randint(60, 14400)
        _data_store["anomaly_reports"].append({
            "summary": random.choice([
                "Unusual whale concentration detected on Merchant Moe MNT/USDC pool",
                "Abnormal transfer pattern: 15 large txs in 30 seconds from related wallets",
                "TVL spike on Agni Finance — possible flash loan activity",
                "Token flow reversal: net inflow changed to massive outflow",
                "Wash trading indicators detected on Fluxion DEX pair",
            ]),
            "market_sentiment": random.choice(["bullish", "bearish", "neutral"]),
            "confidence": round(random.uniform(0.7, 0.95), 2),
            "severity": random.choice(["low", "medium", "high", "critical"]),
            "timestamp": ts,
        })


_seed_demo_data()


# ── Routes ──────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Render the main dashboard page."""
    return templates.TemplateResponse(request, "index.html")


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "service": "mantle-alpha", "version": "0.2.0"}


@app.get("/api/stats")
async def get_stats() -> dict:
    """Summary statistics for the dashboard stats bar."""
    idx = _get_indexer_stats()
    return {
        "total_whale_events": len(_data_store["whale_events"]),
        "active_signals": len(_data_store["signals"]),
        "anomalies_detected": len(_data_store["anomaly_reports"]),
        "total_swaps": len(_data_store["dex_swaps"]),
        "mnt_price": round(random.uniform(1.05, 1.35), 4),
        "mnt_price_change_24h": round(random.uniform(-5, 8), 2),
        "uptime_seconds": int(time.time() - app.state.start_time) if hasattr(app.state, "start_time") else 0,
        "indexer_blocks_processed": idx.get("blocks_processed", 0),
        "indexer_errors": idx.get("errors", 0),
    }


@app.get("/api/whale-events")
async def get_whale_events(limit: int = 20) -> dict:
    events = sorted(_data_store["whale_events"], key=lambda x: x.get("timestamp", 0), reverse=True)
    return {"events": events[:limit]}


@app.get("/api/dex-swaps")
async def get_dex_swaps(limit: int = 30) -> dict:
    swaps = sorted(_data_store["dex_swaps"], key=lambda x: x.get("timestamp", 0), reverse=True)
    return {"swaps": swaps[:limit]}


@app.get("/api/signals")
async def get_signals(limit: int = 10) -> dict:
    signals = sorted(_data_store["signals"], key=lambda x: x.get("timestamp", 0), reverse=True)
    return {"signals": signals[:limit]}


@app.get("/api/anomalies")
async def get_anomalies(limit: int = 10) -> dict:
    reports = sorted(_data_store["anomaly_reports"], key=lambda x: x.get("timestamp", 0), reverse=True)
    return {"reports": reports[:limit]}


@app.get("/api/protocol-health")
async def get_protocol_health() -> dict:
    """TVL and volume metrics per DEX."""
    return {
        "protocols": [
            {
                "name": "Merchant Moe",
                "tvl": 45_200_000 + random.randint(-500000, 500000),
                "volume_24h": 12_800_000 + random.randint(-200000, 200000),
                "change_24h": round(random.uniform(-3, 6), 2),
                "pools": 42,
            },
            {
                "name": "Agni Finance",
                "tvl": 32_100_000 + random.randint(-300000, 300000),
                "volume_24h": 8_400_000 + random.randint(-150000, 150000),
                "change_24h": round(random.uniform(-4, 8), 2),
                "pools": 28,
            },
            {
                "name": "Fluxion",
                "tvl": 18_700_000 + random.randint(-200000, 200000),
                "volume_24h": 5_600_000 + random.randint(-100000, 100000),
                "change_24h": round(random.uniform(-5, 10), 2),
                "pools": 15,
            },
        ],
        "total_tvl": 96_000_000,
        "total_volume_24h": 26_800_000,
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
