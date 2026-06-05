#!/usr/bin/env python3
"""
Launch both the MantleAlpha indexer and dashboard server in parallel.

Usage:
    python scripts/run_all.py

Starts the FastAPI dashboard on the configured host/port, then runs the
blockchain indexer main loop.  Both run concurrently via threading.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path

# ── Path setup ──────────────────────────────────────────────
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-25s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("run_all")


def start_dashboard() -> None:
    """Run the FastAPI dashboard server (blocking, in a thread)."""
    import uvicorn
    from dashboard.app import app  # noqa: F401 — triggers module registration

    logger.info(
        "Starting dashboard on http://%s:%d",
        settings.dashboard_host,
        settings.dashboard_port,
    )
    uvicorn.run(
        app,
        host=settings.dashboard_host,
        port=settings.dashboard_port,
        log_level="info",
        access_log=False,
    )


def main() -> None:
    """Launch dashboard (background thread) + indexer (main thread)."""
    logger.info("=" * 60)
    logger.info("  MantleAlpha — Starting All Services")
    logger.info("=" * 60)

    # ── Dashboard in background thread ─────────────────────
    dashboard_thread = threading.Thread(
        target=start_dashboard,
        name="dashboard",
        daemon=True,  # Dies when main thread exits
    )
    dashboard_thread.start()
    logger.info("Dashboard thread started (port %d)", settings.dashboard_port)

    # Give the server a moment to bind
    time.sleep(2)

    # ── Indexer in main thread (has signal handlers) ───────
    logger.info("Starting indexer in main thread...")
    from scripts.run_indexer import run_indexer
    import asyncio

    try:
        asyncio.run(run_indexer())
    except KeyboardInterrupt:
        logger.info("Interrupted — shutting down")
    finally:
        logger.info("All services stopped.")


if __name__ == "__main__":
    main()
