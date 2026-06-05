#!/usr/bin/env python3
"""
Standalone runner for the Mantle Alpha Telegram bot.

Starts the interactive Telegram bot with command polling, ready
to receive user commands and send alerts. The indexer can run
separately and push data to the bot's shared state.

Usage:
    python scripts/run_bot.py
"""

import asyncio
import logging
import signal
import sys
from pathlib import Path

# Ensure project root is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from alerts.telegram_bot import TelegramBot, BotState

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-20s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("bot")


async def main() -> None:
    """Start the Telegram bot and keep it running."""
    logger.info("Starting Mantle Alpha Telegram Bot (standalone)...")

    if not settings.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN not set — configure .env first")
        sys.exit(1)

    state = BotState()
    bot = TelegramBot(state=state)

    await bot.start()

    logger.info("Bot is running. Press Ctrl+C to stop.")
    logger.info("Listening for commands: /start /status /whales /signals /anomalies")

    # Keep alive until interrupted
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    await stop_event.wait()

    logger.info("Shutting down...")
    await bot.stop()
    logger.info("Bot stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped.")
