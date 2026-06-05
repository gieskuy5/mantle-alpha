"""
Centralized configuration for Mantle Alpha.
All values can be overridden via environment variables.
"""

import os
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # ── Mantle Network ──────────────────────────────────────
    mantle_rpc_url: str = Field(
        default="https://rpc.mantle.xyz",
        description="Mantle Network JSON-RPC endpoint",
    )
    mantle_chain_id: int = Field(default=5000, description="Mantle chain ID")

    # ── AI / LLM ───────────────────────────────────────────
    openai_api_key: str = Field(default="", description="OpenAI API key")
    openai_model: str = Field(
        default="gpt-4o-mini", description="Model for anomaly detection"
    )

    # ── Telegram ───────────────────────────────────────────
    telegram_bot_token: str = Field(default="", description="Telegram bot token")
    telegram_chat_id: str = Field(default="", description="Target chat ID for alerts")

    # ── Whale Tracking ─────────────────────────────────────
    whale_threshold_mnt: float = Field(
        default=10_000.0, description="Min MNT balance to track as whale"
    )
    whale_wallets: list[str] = Field(
        default_factory=list,
        description="Hardcoded whale wallet addresses to watch",
    )

    # ── DEX Contracts ──────────────────────────────────────
    merchant_moe_router: str = Field(
        default="0x0000000000000000000000000000000000000000",
        description="Merchant Moe router address on Mantle",
    )
    agni_finance_router: str = Field(
        default="0x0000000000000000000000000000000000000000",
        description="Agni Finance router address on Mantle",
    )
    fluxion_router: str = Field(
        default="0x0000000000000000000000000000000000000000",
        description="Fluxion router address on Mantle",
    )

    # ── Runtime ────────────────────────────────────────────
    poll_interval_sec: int = Field(
        default=5, description="Seconds between block polls"
    )
    dashboard_host: str = Field(default="0.0.0.0", description="Dashboard bind host")
    dashboard_port: int = Field(default=8000, description="Dashboard bind port")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
