"""
Telegram bot for Mantle Alpha alerts.

Sends formatted notifications about whale movements, anomaly detections,
and trading signals to a configured Telegram chat.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from config import settings

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}"


class TelegramBot:
    """
    Lightweight Telegram bot for sending alerts.

    Uses the Telegram Bot API directly (no polling) — this bot is
    designed for outbound notifications only.
    """

    def __init__(self, token: str | None = None, chat_id: str | None = None) -> None:
        self.token = token or settings.telegram_bot_token
        self.chat_id = chat_id or settings.telegram_chat_id
        self._base_url = TELEGRAM_API.format(token=self.token)

    async def send_message(self, text: str, parse_mode: str = "HTML") -> dict | None:
        """Send a text message to the configured chat."""
        if not self.token or not self.chat_id:
            logger.warning("Telegram bot not configured — skipping message")
            return None

        url = f"{self._base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=payload, timeout=10)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("Telegram API error %s: %s", e.response.status_code, e.response.text)
        except Exception:
            logger.exception("Failed to send Telegram message")
        return None

    # ── Formatted Alert Methods ─────────────────────────────

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
        for a in anomalies[:5]:  # Cap at 5
            severity_icon = {"critical": "🚨", "high": "⚠️", "medium": "📊", "low": "ℹ️"}.get(
                a.get("severity", "low"), "ℹ️"
            )
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
        return await self.send_message(msg)

    # ── Sync Wrapper ────────────────────────────────────────

    def send_message_sync(self, text: str, parse_mode: str = "HTML") -> dict | None:
        """Synchronous wrapper for send_message."""
        return asyncio.run(self.send_message(text, parse_mode))
