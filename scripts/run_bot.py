#!/usr/bin/env python3
"""
Start the Mantle Alpha Telegram bot.

This script initializes the Telegram bot and keeps it running
to receive and respond to commands.
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from alerts.telegram_bot import TelegramBot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-20s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("bot")


async def main() -> None:
    """Start the Telegram bot and send a test message."""
    logger.info("Starting Mantle Alpha Telegram Bot...")

    if not settings.telegram_bot_token:
        logger.error("TELEGRAM_BOT_TOKEN not set — configure .env first")
        sys.exit(1)

    if not settings.telegram_chat_id:
        logger.error("TELEGRAM_CHAT_ID not set — configure .env first")
        sys.exit(1)

    bot = TelegramBot()

    # Send startup message
    await bot.send_message(
        "🧠 <b>Mantle Alpha Bot Started</b>\n\n"
        "Monitoring Mantle Network for smart money movements.\n"
        "You will receive alerts for:\n"
        "• 🐋 Whale wallet activity\n"
        "• 🧠 AI anomaly detections\n"
        "• 📈 Trading signals\n\n"
        "<i>Track 2 — Mantle Turing Test Hackathon 2026</i>"
    )

    logger.info("Bot is running. Waiting for alerts...")
    logger.info("Press Ctrl+C to stop.")

    # Keep the process alive — alerts are sent by the indexer
    try:
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        await bot.send_message("🔴 <b>Mantle Alpha Bot Stopped</b>")


if __name__ == "__main__":
    asyncio.run(main())
