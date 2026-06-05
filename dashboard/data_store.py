"""
Shared in-memory data store for MantleAlpha.

Importable by both the dashboard and the indexer so they share the same data.
"""

import time

data_store: dict = {
    "whale_events": [],
    "dex_swaps": [],
    "anomaly_reports": [],
    "signals": [],
    "indexer_stats": {
        "blocks_processed": 0,
        "whale_events_detected": 0,
        "swaps_detected": 0,
        "anomalies_detected": 0,
        "signals_generated": 0,
        "errors": 0,
        "start_time": time.time(),
    },
}


def add_whale_event(event: dict) -> None:
    event.setdefault("timestamp", time.time())
    data_store["whale_events"].append(event)
    # Keep last 1000
    if len(data_store["whale_events"]) > 1000:
        data_store["whale_events"] = data_store["whale_events"][-500:]


def add_dex_swap(swap: dict) -> None:
    swap.setdefault("timestamp", time.time())
    data_store["dex_swaps"].append(swap)
    if len(data_store["dex_swaps"]) > 2000:
        data_store["dex_swaps"] = data_store["dex_swaps"][-1000:]


def add_anomaly_report(report: dict) -> None:
    report.setdefault("timestamp", time.time())
    data_store["anomaly_reports"].append(report)
    if len(data_store["anomaly_reports"]) > 200:
        data_store["anomaly_reports"] = data_store["anomaly_reports"][-100:]


def add_signal(signal: dict) -> None:
    signal.setdefault("timestamp", time.time())
    data_store["signals"].append(signal)
    if len(data_store["signals"]) > 200:
        data_store["signals"] = data_store["signals"][-100:]


def get_stats() -> dict:
    return dict(data_store["indexer_stats"])
