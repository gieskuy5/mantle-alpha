#!/usr/bin/env python3
"""
Main indexer loop for Mantle Alpha.

Polls the Mantle Network for new blocks, tracks whale wallet movements,
monitors DEX swaps, runs AI anomaly detection on a timer, and pushes
alerts to Telegram and the shared dashboard data store.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
import time
from pathlib import Path

# ── Path setup ──────────────────────────────────────────────
# When run as `python scripts/run_indexer.py`, ensure project root is on sys.path
# so that `config`, `indexer.*`, `ai.*`, `dashboard.*` resolve correctly.
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from config import settings
from indexer.mantle_client import MantleClient
from indexer.wallet_tracker import WalletTracker, WhaleEvent
from indexer.dex_monitor import DexMonitor, SwapEvent
from indexer.mantle_scan import MantlescanClient
from ai.anomaly_detector import AnomalyDetector
from ai.signal_generator import SignalGenerator
from alerts.telegram_bot import TelegramBot
from dashboard.data_store import (
    data_store as _data_store,
    add_whale_event,
    add_dex_swap,
    add_anomaly_report,
    add_signal,
)

# ── Logging ─────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-25s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("indexer")

# ── Shared state ────────────────────────────────────────────
_shutdown_event = asyncio.Event()


# ================================================================
# Whale Discovery
# ================================================================

async def discover_whales(mantlescan: MantlescanClient) -> list[str]:
    """
    Use MantlescanClient to auto-discover top whale wallets.
    Merges with statically configured wallets from settings.
    Returns a deduplicated list of addresses.
    """
    if not settings.whale_auto_discover:
        logger.info("Whale auto-discovery disabled — using static wallet list only")
        return list(settings.whale_wallets)

    if not settings.mantlescan_api_key:
        logger.warning(
            "MANTLESCAN_API_KEY not set — skipping auto-discovery, using static wallets only"
        )
        return list(settings.whale_wallets)

    try:
        await mantlescan.start()
        wallets = await mantlescan.discover_whale_wallets(count=settings.whale_discover_count)
        await mantlescan.close()
        return wallets
    except Exception:
        logger.exception("Whale auto-discovery failed — falling back to static wallets")
        try:
            await mantlescan.close()
        except Exception:
            pass
        return list(settings.whale_wallets)


# ================================================================
# AI Analysis Cycle
# ================================================================

async def run_ai_analysis(
    anomaly_detector: AnomalyDetector,
    signal_generator: SignalGenerator,
    telegram: TelegramBot,
    event_buffer: list[dict],
    swap_buffer: list[dict],
    last_block: int,
) -> None:
    """
    Run anomaly detection + signal generation on buffered data.
    Sends alerts via Telegram and stores results in the dashboard.
    """
    stats = _data_store["indexer_stats"]

    # ── Anomaly Detection ──────────────────────────────────
    if event_buffer:
        logger.info(
            "Running anomaly detection on %d whale events (blocks ~%d–%d)...",
            len(event_buffer),
            max(0, last_block - 100),
            last_block,
        )
        try:
            report = await asyncio.to_thread(
                anomaly_detector.detect,
                events=event_buffer,
                from_block=max(0, last_block - 100),
                to_block=last_block,
                time_window_min=max(1, settings.ai_analysis_interval // 60),
            )

            if report.anomalies_detected:
                logger.warning("⚠️  Anomalies detected: %s", report.summary)
                anomaly_dicts = [
                    {
                        "type": a.type,
                        "severity": a.severity,
                        "description": a.description,
                        "suggested_action": a.suggested_action,
                        "wallet": a.wallet,
                    }
                    for a in report.anomalies
                ]
                # Telegram
                await telegram.send_anomaly_alert(
                    summary=report.summary,
                    anomalies=anomaly_dicts,
                    sentiment=report.market_sentiment,
                )
                # Dashboard
                add_anomaly_report({
                    "summary": report.summary,
                    "market_sentiment": report.market_sentiment,
                    "confidence": report.confidence,
                    "anomalies": anomaly_dicts,
                    "block_range": [max(0, last_block - 100), last_block],
                })
                stats["anomalies_detected"] += len(report.anomalies)
            else:
                logger.info("No anomalies detected (confidence=%.2f)", report.confidence)

        except Exception:
            logger.exception("Anomaly detection failed")

    # ── Signal Generation ──────────────────────────────────
    if event_buffer or swap_buffer:
        logger.info(
            "Running signal generation on %d events + %d swaps...",
            len(event_buffer),
            len(swap_buffer),
        )
        try:
            sig_report = await asyncio.to_thread(
                signal_generator.generate,
                whale_events=event_buffer,
                dex_swaps=swap_buffer,
            )

            if sig_report.signals:
                logger.info("Generated %d trading signals", len(sig_report.signals))
                signal_dicts = [
                    {
                        "token": s.token,
                        "action": s.action,
                        "confidence": s.confidence,
                        "timeframe": s.timeframe,
                        "reasoning": s.reasoning,
                        "whale_supporting": s.whale_supporting,
                    }
                    for s in sig_report.signals
                ]
                # Telegram
                await telegram.send_signal_alert(
                    signals=signal_dicts,
                    sentiment=sig_report.overall_sentiment,
                    risk_level=sig_report.risk_level,
                )
                # Dashboard
                for sd in signal_dicts:
                    add_signal(sd)
                stats["signals_generated"] += len(sig_report.signals)
            else:
                logger.info("No signals generated")

        except Exception:
            logger.exception("Signal generation failed")


# ================================================================
# Stats Logger
# ================================================================

def log_stats() -> None:
    """Log periodic indexer statistics."""
    stats = _data_store["indexer_stats"]
    uptime = time.time() - stats["start_time"]
    hours = int(uptime // 3600)
    minutes = int((uptime % 3600) // 60)
    seconds = int(uptime % 60)

    logger.info(
        "📊 Stats | blocks=%d | whale_events=%d | swaps=%d | "
        "anomalies=%d | signals=%d | errors=%d | uptime=%dh%02dm%02ds",
        stats["blocks_processed"],
        stats["whale_events_detected"],
        stats["swaps_detected"],
        stats["anomalies_detected"],
        stats["signals_generated"],
        stats["errors"],
        hours,
        minutes,
        seconds,
    )


# ================================================================
# Main Indexer Loop
# ================================================================

async def run_indexer() -> None:
    """
    Main indexer loop — polls blocks, tracks whales, monitors DEX swaps,
    runs AI analysis on a timer, sends alerts, stores results.
    """
    logger.info("=" * 60)
    logger.info("  Mantle Alpha Indexer — Starting")
    logger.info("=" * 60)
    logger.info("RPC endpoint     : %s", settings.mantle_rpc_url)
    logger.info("Poll interval    : %ds", settings.poll_interval_sec)
    logger.info("AI analysis every: %ds", settings.ai_analysis_interval)
    logger.info("Telegram configured: %s", bool(settings.telegram_bot_token and settings.telegram_chat_id))
    logger.info("OpenAI configured  : %s", bool(settings.openai_api_key))

    stats = _data_store["indexer_stats"]

    # ── 1. Connect to Mantle RPC ───────────────────────────
    logger.info("Connecting to Mantle RPC...")
    try:
        client = MantleClient()
    except Exception:
        logger.exception("Failed to create MantleClient")
        sys.exit(1)

    if not client.is_connected():
        logger.error(
            "Cannot connect to Mantle RPC at %s — aborting", settings.mantle_rpc_url
        )
        sys.exit(1)

    chain_id = client.w3.eth.chain_id
    logger.info("✅ Connected to Mantle RPC — chain ID %s", chain_id)

    # ── 2. Auto-discover whale wallets ─────────────────────
    mantlescan = MantlescanClient()
    whale_wallets = await discover_whales(mantlescan)
    logger.info("Tracking %d whale wallets", len(whale_wallets))
    for i, addr in enumerate(whale_wallets[:10]):
        logger.info("  [%d] %s", i + 1, addr)
    if len(whale_wallets) > 10:
        logger.info("  ... and %d more", len(whale_wallets) - 10)

    # ── 3. Initialize components ───────────────────────────
    tracker = WalletTracker(client=client, whale_addresses=whale_wallets)
    dex_monitor = DexMonitor(client=client)
    anomaly_detector = AnomalyDetector()
    signal_generator = SignalGenerator()
    telegram = TelegramBot()

    # ── 4. Set up signal handlers for graceful shutdown ────
    loop = asyncio.get_running_loop()

    def _request_shutdown(sig_name: str) -> None:
        logger.info("Received %s — initiating graceful shutdown...", sig_name)
        _shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _request_shutdown, sig.name)

    # ── 5. Main loop ──────────────────────────────────────
    last_block = await asyncio.to_thread(client.latest_block)
    logger.info("Starting from block %d", last_block)

    event_buffer: list[dict] = []
    swap_buffer: list[dict] = []
    last_analysis_time = time.time()
    last_stats_time = time.time()
    consecutive_errors = 0
    max_consecutive_errors = 20
    stats_log_interval = 120  # Log stats every 2 minutes

    # Send startup notification
    await telegram.send_message(
        f"🚀 <b>Mantle Alpha Indexer Started</b>\n\n"
        f"<b>RPC:</b> <code>{settings.mantle_rpc_url}</code>\n"
        f"<b>Chain:</b> {chain_id}\n"
        f"<b>Whale wallets:</b> {len(whale_wallets)}\n"
        f"<b>Starting block:</b> {last_block}\n"
        f"<b>Poll interval:</b> {settings.poll_interval_sec}s\n"
        f"<b>AI analysis:</b> every {settings.ai_analysis_interval}s"
    )

    while not _shutdown_event.is_set():
        try:
            # Check for new blocks
            current_block = await asyncio.to_thread(client.latest_block)

            if current_block > last_block:
                consecutive_errors = 0  # Reset on success
                blocks_behind = current_block - last_block
                logger.info("New block(s): %d → %d (+%d)", last_block, current_block, blocks_behind)

                # ── Whale wallet tracking ──────────────────
                try:
                    whale_events = await asyncio.to_thread(tracker.poll)
                    for event in whale_events:
                        event_dict = {
                            "address": event.address,
                            "event_type": event.event_type,
                            "amount_mnt": event.amount_mnt,
                            "block_number": event.block_number,
                            "details": event.details,
                        }
                        event_buffer.append(event_dict)
                        add_whale_event(event_dict)
                        stats["whale_events_detected"] += 1

                        # Immediate whale alert
                        await telegram.send_whale_alert(
                            address=event.address,
                            event_type=event.event_type,
                            amount_mnt=event.amount_mnt,
                            block=event.block_number,
                        )

                    if whale_events:
                        logger.info("Detected %d whale event(s) this block", len(whale_events))

                except Exception:
                    logger.exception("Error polling whale wallets")
                    stats["errors"] += 1

                # ── DEX swap monitoring ────────────────────
                # Scan up to 5 blocks behind to avoid missing events
                scan_start = max(last_block, current_block - 5)
                for blk in range(scan_start, current_block + 1):
                    try:
                        swaps = await asyncio.to_thread(
                            dex_monitor.get_swaps_in_block, blk
                        )
                        for swap in swaps:
                            swap_dict = {
                                "dex": swap.dex,
                                "tx_hash": swap.tx_hash,
                                "block_number": swap.block_number,
                                "sender": swap.sender,
                                "to": swap.to,
                                "amount_in": swap.amount_in,
                                "amount_out": swap.amount_out,
                                "pair_address": swap.pair_address,
                            }
                            swap_buffer.append(swap_dict)
                            add_dex_swap(swap_dict)
                            stats["swaps_detected"] += 1
                    except Exception as exc:
                        logger.debug("Error scanning block %d for swaps: %s", blk, exc)

                if swap_buffer:
                    logger.info("Detected %d DEX swap(s) in blocks %d–%d",
                                len(swap_buffer), scan_start, current_block)

                last_block = current_block
                stats["blocks_processed"] += blocks_behind

            # ── AI analysis on interval ────────────────────
            now = time.time()
            if (now - last_analysis_time >= settings.ai_analysis_interval
                    and (event_buffer or swap_buffer)):
                await run_ai_analysis(
                    anomaly_detector=anomaly_detector,
                    signal_generator=signal_generator,
                    telegram=telegram,
                    event_buffer=list(event_buffer),  # snapshot
                    swap_buffer=list(swap_buffer),     # snapshot
                    last_block=last_block,
                )
                event_buffer.clear()
                swap_buffer.clear()
                last_analysis_time = now

            # ── Stats logging ──────────────────────────────
            if now - last_stats_time >= stats_log_interval:
                log_stats()
                last_stats_time = now

            # Sleep until next poll
            try:
                await asyncio.wait_for(
                    _shutdown_event.wait(), timeout=settings.poll_interval_sec
                )
                # If we get here, shutdown was requested
                break
            except asyncio.TimeoutError:
                pass  # Normal — timeout means we poll again

        except KeyboardInterrupt:
            logger.info("Indexer stopped by user (KeyboardInterrupt)")
            break

        except Exception:
            consecutive_errors += 1
            stats["errors"] += 1
            logger.exception("Error in indexer loop (consecutive=%d)", consecutive_errors)

            if consecutive_errors >= max_consecutive_errors:
                logger.critical(
                    "Too many consecutive errors (%d) — aborting", consecutive_errors
                )
                await telegram.send_message(
                    f"🚨 <b>Indexer CRASHED</b>\n\n"
                    f"Too many consecutive errors ({consecutive_errors}). Aborting."
                )
                sys.exit(1)

            # Exponential backoff on errors, capped at 60s
            backoff = min(settings.poll_interval_sec * (2 ** consecutive_errors), 60)
            logger.info("Retrying in %ds...", backoff)
            try:
                await asyncio.wait_for(_shutdown_event.wait(), timeout=backoff)
                break
            except asyncio.TimeoutError:
                pass

    # ── Shutdown ───────────────────────────────────────────
    logger.info("Shutting down indexer...")
    log_stats()

    # Clean up MantlescanClient if it was left open
    try:
        await mantlescan.close()
    except Exception:
        pass

    await telegram.send_message(
        f"⏹️ <b>Mantle Alpha Indexer Stopped</b>\n\n"
        f"<b>Blocks processed:</b> {stats['blocks_processed']}\n"
        f"<b>Whale events:</b> {stats['whale_events_detected']}\n"
        f"<b>Swaps detected:</b> {stats['swaps_detected']}\n"
        f"<b>Uptime:</b> {int(time.time() - stats['start_time'])}s"
    )

    logger.info("Indexer stopped cleanly.")


# ================================================================
# Entry point
# ================================================================

def main() -> None:
    """Synchronous entry point — runs the async indexer loop."""
    try:
        asyncio.run(run_indexer())
    except KeyboardInterrupt:
        logger.info("Interrupted — exiting")


if __name__ == "__main__":
    main()
