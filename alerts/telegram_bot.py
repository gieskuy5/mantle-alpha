"""
Interactive Telegram bot for Mantle Alpha.

Provides real-time alerts for whale movements, anomaly detections, and
trading signals, plus interactive commands for querying the current
state of the indexer and AI engine.

Uses python-telegram-bot v20+ (Application) for command handling with
polling in a background thread. Includes a message queue with rate
limiting and exponential-backoff retries.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy import helper for python-telegram-bot
# ---------------------------------------------------------------------------

_ptb = None  # cached module


def _import_ptb():
    """Import and cache the python-telegram-bot package."""
    global _ptb
    if _ptb is None:
        import telegram
        from telegram import Update
        from telegram.ext import Application, CommandHandler, ContextTypes
        from telegram.constants import ParseMode
        _ptb = {
            "telegram": telegram,
            "Update": Update,
            "Application": Application,
            "CommandHandler": CommandHandler,
            "ContextTypes": ContextTypes,
            "ParseMode": ParseMode,
        }
    return _ptb


# ---------------------------------------------------------------------------
# Data structures for bot state
# ---------------------------------------------------------------------------

@dataclass
class BotState:
    """Shared mutable state between the bot commands and the indexer."""

    # Subscriber chat IDs
    subscribers: set[int] = field(default_factory=set)

    # Indexer runtime stats
    blocks_processed: int = 0
    events_detected: int = 0
    start_time: float = field(default_factory=time.time)

    # Latest whale snapshots {address: {"balance_mnt": float, "block": int}}
    whale_snapshots: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Recent signals (most recent first, capped at 20)
    recent_signals: list[dict[str, Any]] = field(default_factory=list)

    # Recent anomalies (most recent first, capped at 20)
    recent_anomalies: list[dict[str, Any]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Message queue with rate-limiting and retries
# ---------------------------------------------------------------------------

@dataclass
class _QueuedMessage:
    """A single message waiting to be sent."""
    chat_id: int | str
    text: str
    parse_mode: str = "HTML"
    attempts: int = 0
    max_attempts: int = 5
    next_attempt_at: float = 0.0  # epoch seconds


class MessageQueue:
    """
    Async message queue that rate-limits outbound Telegram messages
    to at most 1 message/second and retries failures with exponential
    backoff (base 2s, capped at 60s).
    """

    RATE_LIMIT_INTERVAL = 1.0  # seconds between sends
    BACKOFF_BASE = 2.0         # seconds
    BACKOFF_CAP = 60.0         # max wait

    def __init__(self) -> None:
        self._queue: deque[_QueuedMessage] = deque()
        self._lock = asyncio.Lock()
        self._send_fn: Any = None  # set by TelegramBot
        self._task: asyncio.Task | None = None
        self._running = False

    def set_send_fn(self, fn) -> None:
        """Set the async callable that actually sends a message."""
        self._send_fn = fn

    def enqueue(
        self,
        chat_id: int | str,
        text: str,
        parse_mode: str = "HTML",
        max_attempts: int = 5,
    ) -> None:
        """Add a message to the queue."""
        msg = _QueuedMessage(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            max_attempts=max_attempts,
        )
        self._queue.append(msg)

    async def start(self) -> None:
        """Start the background drain loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._drain_loop())
        logger.info("Message queue started")

    async def stop(self) -> None:
        """Stop the drain loop gracefully."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Message queue stopped (%d unsent)", len(self._queue))

    async def _drain_loop(self) -> None:
        """Continuously drain the queue respecting the rate limit."""
        while self._running:
            now = time.time()
            msg: _QueuedMessage | None = None

            async with self._lock:
                # Find the first message ready to send
                for i, m in enumerate(self._queue):
                    if m.next_attempt_at <= now:
                        msg = self._queue[i]
                        del self._queue[i]
                        break

            if msg is None:
                # Nothing ready — sleep briefly then check again
                await asyncio.sleep(0.1)
                continue

            # Send
            if self._send_fn is None:
                logger.error("MessageQueue: no send_fn configured — dropping message")
                continue

            try:
                await self._send_fn(msg.chat_id, msg.text, msg.parse_mode)
            except Exception as exc:
                msg.attempts += 1
                if msg.attempts < msg.max_attempts:
                    backoff = min(
                        self.BACKOFF_BASE ** msg.attempts,
                        self.BACKOFF_CAP,
                    )
                    msg.next_attempt_at = time.time() + backoff
                    async with self._lock:
                        self._queue.appendleft(msg)  # re-queue at front
                    logger.warning(
                        "Send failed (attempt %d/%d), retrying in %.1fs: %s",
                        msg.attempts,
                        msg.max_attempts,
                        backoff,
                        exc,
                    )
                else:
                    logger.error(
                        "Message dropped after %d attempts: %s",
                        msg.attempts,
                        exc,
                    )

            # Rate limit: wait before sending next
            await asyncio.sleep(self.RATE_LIMIT_INTERVAL)


# ---------------------------------------------------------------------------
# TelegramBot
# ---------------------------------------------------------------------------

class TelegramBot:
    """
    Full interactive Telegram bot for Mantle Alpha.

    * Outbound alerts via ``send_whale_alert``, ``send_anomaly_alert``,
      ``send_signal_alert`` — queued and rate-limited.
    * Interactive commands: /start, /status, /whales, /signals,
      /anomalies, /subscribe, /unsubscribe, /help.
    * Polling runs in a background thread so it doesn't block the
      main indexer event loop.
    """

    def __init__(
        self,
        token: str | None = None,
        chat_id: str | None = None,
        state: BotState | None = None,
    ) -> None:
        self.token = token or settings.telegram_bot_token
        self.chat_id = chat_id or settings.telegram_chat_id
        self.state = state or BotState()

        self._queue = MessageQueue()
        self._queue.set_send_fn(self._raw_send)

        self._app: Any = None  # telegram.ext.Application
        self._polling_task: asyncio.Task | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    # ── Lifecycle ────────────────────────────────────────────

    async def start(self) -> None:
        """
        Start the bot: register commands, begin polling, and start
        the message queue. Safe to call from an existing event loop.
        """
        if not self.token:
            logger.warning("Telegram bot token not set — bot disabled")
            return

        ptb = _import_ptb()
        Application = ptb["Application"]
        CommandHandler = ptb["CommandHandler"]

        self._app = (
            Application.builder()
            .token(self.token)
            .build()
        )

        # Register commands
        self._app.add_handler(CommandHandler("start", self._cmd_start))
        self._app.add_handler(CommandHandler("help", self._cmd_help))
        self._app.add_handler(CommandHandler("status", self._cmd_status))
        self._app.add_handler(CommandHandler("whales", self._cmd_whales))
        self._app.add_handler(CommandHandler("signals", self._cmd_signals))
        self._app.add_handler(CommandHandler("anomalies", self._cmd_anomalies))
        self._app.add_handler(CommandHandler("subscribe", self._cmd_subscribe))
        self._app.add_handler(CommandHandler("unsubscribe", self._cmd_unsubscribe))

        # Start message queue
        await self._queue.start()

        # Start polling in background
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)

        # Auto-subscribe the configured default chat if set
        if self.chat_id:
            try:
                self.state.subscribers.add(int(self.chat_id))
            except (ValueError, TypeError):
                pass

        logger.info("Telegram bot started — listening for commands")

    async def stop(self) -> None:
        """Gracefully stop the bot."""
        await self._queue.stop()
        if self._app:
            try:
                await self._app.updater.stop()
                await self._app.stop()
                await self._app.shutdown()
            except Exception:
                logger.exception("Error stopping Telegram bot")
        logger.info("Telegram bot stopped")

    def run_in_background(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        """
        Start the bot in a background task of the given (or current)
        event loop. The indexer can continue working in the foreground.
        """
        self._loop = loop or asyncio.get_event_loop()
        self._polling_task = self._loop.create_task(self.start())

    # ── Internal send (used by queue) ────────────────────────

    async def _raw_send(
        self, chat_id: int | str, text: str, parse_mode: str = "HTML"
    ) -> None:
        """Low-level send via the bot's sendMessage API."""
        if not self._app or not self._app.bot:
            raise RuntimeError("Bot not initialised")
        await self._app.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=parse_mode,
            disable_web_page_preview=True,
        )

    # ── Public alert API (backwards compatible) ──────────────

    def _enqueue_for_subscribers(self, text: str) -> None:
        """Push a message to every subscribed chat."""
        if not self.state.subscribers:
            # Fallback to default chat_id
            if self.chat_id:
                self._queue.enqueue(self.chat_id, text)
            return
        for cid in self.state.subscribers:
            self._queue.enqueue(cid, text)

    async def send_message(self, text: str, parse_mode: str = "HTML") -> dict | None:
        """Send a text message (queued). Kept for backwards compatibility."""
        if not self.token:
            logger.warning("Telegram bot not configured — skipping message")
            return None
        self._enqueue_for_subscribers(text)
        return {"status": "queued"}

    def send_message_sync(self, text: str, parse_mode: str = "HTML") -> dict | None:
        """Synchronous wrapper for send_message."""
        return asyncio.run(self.send_message(text, parse_mode))

    # ── Formatted Alert Methods ──────────────────────────────

    async def send_whale_alert(
        self, address: str, event_type: str, amount_mnt: float, block: int
    ) -> dict | None:
        """Send a whale movement alert."""
        emoji = "🟢" if "increase" in event_type else "🔴"
        msg = (
            f"{emoji} <b>Whale Alert</b>\n\n"
            f"<b>Wallet:</b> <code>{address[:6]}...{address[-4:]}</code>\n"
            f"<b>Event:</b> {event_type.replace('_', ' ').title()}\n"
            f"<b>Amount:</b> {amount_mnt:,.4f} MNT\n"
            f"<b>Block:</b> {block}\n"
        )
        return await self.send_message(msg)

    async def send_anomaly_alert(
        self, summary: str, anomalies: list[dict[str, Any]], sentiment: str
    ) -> dict | None:
        """Send an anomaly detection alert."""
        sentiment_emoji = {"bullish": "🟢", "bearish": "🔴", "neutral": "⚪"}.get(
            sentiment, "⚪"
        )

        anomaly_lines = []
        for a in anomalies[:5]:
            severity_icon = {
                "critical": "🚨", "high": "⚠️", "medium": "📊", "low": "ℹ️"
            }.get(a.get("severity", "low"), "ℹ️")
            anomaly_lines.append(
                f"  {severity_icon} <b>{a.get('type', 'unknown').upper()}</b>: "
                f"{a.get('description', 'N/A')}"
            )

        msg = (
            f"🧠 <b>AI Anomaly Report</b>\n\n"
            f"{sentiment_emoji} <b>Sentiment:</b> {sentiment.title()}\n"
            f"<b>Summary:</b> {summary}\n\n"
            f"<b>Anomalies:</b>\n" + "\n".join(anomaly_lines)
        )

        # Store in state for /anomalies command
        for a in anomalies[:5]:
            self.state.recent_anomalies.insert(0, a)
        self.state.recent_anomalies = self.state.recent_anomalies[:20]

        return await self.send_message(msg)

    async def send_signal_alert(
        self, signals: list[dict[str, Any]], sentiment: str, risk_level: str
    ) -> dict | None:
        """Send a trading signal alert."""
        signal_lines = []
        for s in signals[:5]:
            action_emoji = {"buy": "🟢", "sell": "🔴", "hold": "⏸️"}.get(
                s.get("action", "hold"), "❓"
            )
            signal_lines.append(
                f"  {action_emoji} <b>{s.get('token', '?')}</b>: "
                f"{s.get('action', '?').upper()} "
                f"(conf: {s.get('confidence', 0):.0%}) — "
                f"{s.get('reasoning', 'N/A')}"
            )

        msg = (
            f"📈 <b>Trading Signals</b>\n\n"
            f"<b>Sentiment:</b> {sentiment.title()} | "
            f"<b>Risk:</b> {risk_level.title()}\n\n"
            + "\n".join(signal_lines)
        )

        # Store in state for /signals command
        for s in signals[:5]:
            self.state.recent_signals.insert(0, s)
        self.state.recent_signals = self.state.recent_signals[:20]

        return await self.send_message(msg)

    # ── Interactive Command Handlers ─────────────────────────

    async def _cmd_start(self, update, context) -> None:
        """Handle /start — welcome message."""
        ptb = _import_ptb()
        ParseMode = ptb["ParseMode"]

        msg = (
            "🐋 <b>Welcome to Mantle Alpha Bot!</b>\n\n"
            "Your AI-powered smart money tracker on Mantle Network.\n\n"
            "🔥 <b>Features:</b>\n"
            "  • 🐋 Real-time whale wallet monitoring\n"
            "  • 🧠 AI-powered anomaly detection\n"
            "  • 📈 LLM-generated trading signals\n"
            "  • ⚡ Instant Telegram alerts\n\n"
            "📋 <b>Commands:</b>\n"
            "  /status — Indexer status &amp; uptime\n"
            "  /whales — Tracked whale wallets\n"
            "  /signals — Latest trading signals\n"
            "  /anomalies — Recent anomalies\n"
            "  /subscribe — Enable alerts\n"
            "  /unsubscribe — Disable alerts\n"
            "  /help — Show this message\n\n"
            "<i>Track 2 — Mantle Turing Test Hackathon 2026</i>"
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

    async def _cmd_help(self, update, context) -> None:
        """Handle /help — same as /start."""
        await self._cmd_start(update, context)

    async def _cmd_status(self, update, context) -> None:
        """Handle /status — show indexer stats."""
        ptb = _import_ptb()
        ParseMode = ptb["ParseMode"]

        uptime_sec = time.time() - self.state.start_time
        hours, remainder = divmod(int(uptime_sec), 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{hours}h {minutes}m {seconds}s"

        whales_count = len(self.state.whale_snapshots)
        signals_count = len(self.state.recent_signals)
        anomalies_count = len(self.state.recent_anomalies)
        subscribers_count = len(self.state.subscribers)

        msg = (
            "📊 <b>Mantle Alpha — Status</b>\n\n"
            f"⏱️ <b>Uptime:</b> {uptime_str}\n"
            f"🧱 <b>Blocks Processed:</b> {self.state.blocks_processed:,}\n"
            f"🐋 <b>Events Detected:</b> {self.state.events_detected:,}\n"
            f"👛 <b>Whales Tracked:</b> {whales_count}\n"
            f"📈 <b>Signals Generated:</b> {signals_count}\n"
            f"🧠 <b>Anomalies Found:</b> {anomalies_count}\n"
            f"👥 <b>Subscribers:</b> {subscribers_count}\n"
        )
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

    async def _cmd_whales(self, update, context) -> None:
        """Handle /whales — list tracked whale wallets."""
        ptb = _import_ptb()
        ParseMode = ptb["ParseMode"]

        if not self.state.whale_snapshots:
            await update.message.reply_text(
                "🐋 <b>No whale wallets currently tracked.</b>\n\n"
                "Whales are auto-discovered as the indexer runs.",
                parse_mode=ParseMode.HTML,
            )
            return

        lines = ["🐋 <b>Tracked Whale Wallets</b>\n"]
        for addr, snap in sorted(
            self.state.whale_snapshots.items(),
            key=lambda kv: kv[1].get("balance_mnt", 0),
            reverse=True,
        ):
            balance = snap.get("balance_mnt", 0)
            block = snap.get("block", 0)
            short = f"{addr[:6]}...{addr[-4:]}"
            lines.append(
                f"  💰 <code>{short}</code> — {balance:,.2f} MNT "
                f"(block {block:,})"
            )

        lines.append(f"\n<i>Total: {len(self.state.whale_snapshots)} wallets</i>")
        await update.message.reply_text(
            "\n".join(lines), parse_mode=ParseMode.HTML
        )

    async def _cmd_signals(self, update, context) -> None:
        """Handle /signals — show recent trading signals."""
        ptb = _import_ptb()
        ParseMode = ptb["ParseMode"]

        if not self.state.recent_signals:
            await update.message.reply_text(
                "📈 <b>No trading signals yet.</b>\n\n"
                "Signals are generated by the AI engine as data comes in.",
                parse_mode=ParseMode.HTML,
            )
            return

        lines = ["📈 <b>Latest Trading Signals</b>\n"]
        for s in self.state.recent_signals[:10]:
            action_emoji = {"buy": "🟢", "sell": "🔴", "hold": "⏸️"}.get(
                s.get("action", "hold"), "❓"
            )
            lines.append(
                f"  {action_emoji} <b>{s.get('token', '?')}</b>: "
                f"{s.get('action', '?').upper()} "
                f"(conf: {s.get('confidence', 0):.0%})\n"
                f"     {s.get('reasoning', 'N/A')}"
            )

        await update.message.reply_text(
            "\n".join(lines), parse_mode=ParseMode.HTML
        )

    async def _cmd_anomalies(self, update, context) -> None:
        """Handle /anomalies — show recent anomalies."""
        ptb = _import_ptb()
        ParseMode = ptb["ParseMode"]

        if not self.state.recent_anomalies:
            await update.message.reply_text(
                "🧠 <b>No anomalies detected.</b>\n\n"
                "The AI engine monitors for unusual patterns continuously.",
                parse_mode=ParseMode.HTML,
            )
            return

        lines = ["🧠 <b>Recent Anomalies</b>\n"]
        for a in self.state.recent_anomalies[:10]:
            severity_icon = {
                "critical": "🚨", "high": "⚠️", "medium": "📊", "low": "ℹ️"
            }.get(a.get("severity", "low"), "ℹ️")
            lines.append(
                f"  {severity_icon} <b>{a.get('type', 'unknown').upper()}</b> "
                f"[{a.get('severity', '?')}]\n"
                f"     {a.get('description', 'N/A')}"
            )

        await update.message.reply_text(
            "\n".join(lines), parse_mode=ParseMode.HTML
        )

    async def _cmd_subscribe(self, update, context) -> None:
        """Handle /subscribe — enable alerts for this chat."""
        ptb = _import_ptb()
        ParseMode = ptb["ParseMode"]

        chat_id = update.effective_chat.id
        self.state.subscribers.add(chat_id)

        await update.message.reply_text(
            "✅ <b>Subscribed!</b>\n\n"
            "You will now receive real-time alerts for:\n"
            "  • 🐋 Whale movements\n"
            "  • 🧠 AI anomaly detections\n"
            "  • 📈 Trading signals\n\n"
            "Use /unsubscribe to stop.",
            parse_mode=ParseMode.HTML,
        )

    async def _cmd_unsubscribe(self, update, context) -> None:
        """Handle /unsubscribe — disable alerts for this chat."""
        ptb = _import_ptb()
        ParseMode = ptb["ParseMode"]

        chat_id = update.effective_chat.id
        self.state.subscribers.discard(chat_id)

        await update.message.reply_text(
            "🔕 <b>Unsubscribed.</b>\n\n"
            "You will no longer receive alerts.\n"
            "Use /subscribe to re-enable.",
            parse_mode=ParseMode.HTML,
        )
