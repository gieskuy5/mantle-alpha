#!/usr/bin/env python3
"""
Main indexer loop for Mantle Alpha.

Polls the Mantle Network for new blocks, tracks whale wallet movements,
monitors DEX swaps, and runs AI anomaly detection.
"""

import asyncio
import logging
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from indexer.mantle_client import MantleClient
from indexer.wallet_tracker import WalletTracker
from indexer.dex_monitor import DexMonitor
from ai.anomaly_detector import AnomalyDetector
from ai.signal_generator import SignalGenerator
from alerts.telegram_bot import TelegramBot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-25s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("indexer")


async def run_indexer() -> None:
    """Main indexer loop — polls blocks, detects anomalies, sends alerts."""
    logger.info("Starting Mantle Alpha Indexer...")
    logger.info("RPC: %s", settings.mantle_rpc_url)
    logger.info("Poll interval: %ds", settings.poll_interval_sec)

    # Initialize components
    client = MantleClient()
    if not client.is_connected():
        logger.error("Cannot connect to Mantle RPC — aborting")
        sys.exit(1)

    tracker = WalletTracker(client=client)
    dex_monitor = DexMonitor(client=client)
    anomaly_detector = AnomalyDetector()
    signal_generator = SignalGenerator()
    telegram = TelegramBot()

    logger.info("Indexer ready. Watching %d whale wallets...", len(tracker.whale_addresses))

    # If no wallets configured, add a demo address
    if not tracker.whale_addresses:
        logger.info("No whale wallets configured — add addresses to WHALE_WALLETS in config")
        logger.info("Running with DEX monitoring only...")

    last_block = client.latest_block()
    logger.info("Starting from block %d", last_block)

    event_buffer: list[dict] = []
    swap_buffer: list[dict] = []
    analysis_interval = 60  # Run AI analysis every 60 seconds
    last_analysis = time.time()

    while True:
        try:
            current_block = client.latest_block()

            if current_block > last_block:
                blocks_behind = current_block - last_block
                logger.info("New block(s): %d → %d (+%d)", last_block, current_block, blocks_behind)

                # Poll whale wallets
                events = tracker.poll()
                for event in events:
                    event_dict = {
                        "address": event.address,
                        "event_type": event.event_type,
                        "amount_mnt": event.amount_mnt,
                        "block_number": event.block_number,
                        "details": event.details,
                    }
                    event_buffer.append(event_dict)

                    # Send immediate Telegram alert for whale events
                    await telegram.send_whale_alert(
                        address=event.address,
                        event_type=event.event_type,
                        amount_mnt=event.amount_mnt,
                        block=event.block_number,
                    )

                # Monitor DEX swaps (sample recent blocks)
                for blk in range(max(last_block, current_block - 5), current_block + 1):
                    try:
                        swaps = dex_monitor.get_swaps_in_block(blk)
                        for swap in swaps:
                            swap_buffer.append({
                                "dex": swap.dex,
                                "tx_hash": swap.tx_hash,
                                "block_number": swap.block_number,
                                "sender": swap.sender,
                                "amount_in": swap.amount_in,
                                "amount_out": swap.amount_out,
                            })
                    except Exception:
                        pass  # Non-critical

                last_block = current_block

            # Periodic AI analysis
            now = time.time()
            if now - last_analysis >= analysis_interval and (event_buffer or swap_buffer):
                logger.info(
                    "Running AI analysis on %d events, %d swaps...",
                    len(event_buffer),
                    len(swap_buffer),
                )

                # Anomaly detection
                if event_buffer:
                    report = anomaly_detector.detect(
                        events=event_buffer,
                        from_block=last_block - 100,
                        to_block=last_block,
                    )
                    if report.anomalies_detected:
                        logger.warning("⚠️  Anomalies detected: %s", report.summary)
                        await telegram.send_anomaly_alert(
                            summary=report.summary,
                            anomalies=[
                                {
                                    "type": a.type,
                                    "severity": a.severity,
                                    "description": a.description,
                                }
                                for a in report.anomalies
                            ],
                            sentiment=report.market_sentiment,
                        )

                # Signal generation
                if event_buffer or swap_buffer:
                    sig_report = signal_generator.generate(
                        whale_events=event_buffer,
                        dex_swaps=swap_buffer,
                    )
                    if sig_report.signals:
                        logger.info("Generated %d trading signals", len(sig_report.signals))
                        await telegram.send_signal_alert(
                            signals=[
                                {
                                    "token": s.token,
                                    "action": s.action,
                                    "confidence": s.confidence,
                                    "reasoning": s.reasoning,
                                }
                                for s in sig_report.signals
                            ],
                            sentiment=sig_report.overall_sentiment,
                            risk_level=sig_report.risk_level,
                        )

                # Clear buffers
                event_buffer.clear()
                swap_buffer.clear()
                last_analysis = now

            time.sleep(settings.poll_interval_sec)

        except KeyboardInterrupt:
            logger.info("Indexer stopped by user")
            break
        except Exception:
            logger.exception("Error in indexer loop")
            time.sleep(settings.poll_interval_sec * 2)


if __name__ == "__main__":
    asyncio.run(run_indexer())
