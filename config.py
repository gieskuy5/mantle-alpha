"""
Centralized configuration for Mantle Alpha.
All values can be overridden via environment variables.
"""

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

    # ── Mantlescan ──────────────────────────────────────────
    mantlescan_api_key: str = Field(
        default="",
        description="API key for https://api.mantlescan.xyz/api",
    )
    mantlescan_api_url: str = Field(
        default="https://api.mantlescan.xyz/api",
        description="Mantlescan API base URL",
    )

    # ── Subgraph ────────────────────────────────────────────
    subgraph_url: str = Field(
        default="https://subgraph-api.mantle.xyz/subgraphs/name",
        description="Mantle subgraph endpoint base URL",
    )

    # ── AI / LLM ───────────────────────────────────────────
    openai_api_key: str = Field(default="", description="OpenAI API key")
    openai_model: str = Field(
        default="gpt-4o-mini", description="Model for anomaly detection"
    )
    llm_base_url: str = Field(
        default="",
        description="Base URL for any OpenAI-compatible LLM endpoint (e.g. https://api.openai.com/v1)",
    )
    llm_api_key: str = Field(
        default="",
        description="Generic LLM API key; falls back to openai_api_key if empty",
    )
    llm_model: str = Field(
        default="gpt-4o-mini",
        description="Model name for LLM calls (e.g. gpt-4o-mini, mimo-v2-pro)",
    )
    ai_analysis_interval: int = Field(
        default=60,
        description="Seconds between AI analysis runs",
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
    whale_auto_discover: bool = Field(
        default=True,
        description="Automatically discover top whale wallets via Mantlescan",
    )
    whale_discover_count: int = Field(
        default=20,
        description="Top N wallets to auto-discover and track",
    )

    # ── Swap Filtering ─────────────────────────────────────
    min_swap_amount_usd: float = Field(
        default=1000.0,
        description="Minimum swap value in USD to report (filters noise)",
    )

    # ── DEX Contracts ──────────────────────────────────────
    merchant_moe_router: str | None = Field(
        default=None,
        description="Merchant Moe router address on Mantle",
    )
    agni_finance_router: str | None = Field(
        default=None,
        description="Agni Finance router address on Mantle",
    )
    fluxion_router: str | None = Field(
        default=None,
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
