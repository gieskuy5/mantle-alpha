"""
Signal generator for Mantle Alpha.

Generates buy/sell/hold trading signals from whale activity data
and DEX swap patterns using LLM analysis.

Falls back to simple momentum-based signals when no LLM is configured.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

import openai

from config import settings
from ai import prompts

logger = logging.getLogger(__name__)

# ── Cache ──────────────────────────────────────────────────

_CACHE_TTL = 30  # seconds


class _ResultCache:
    """Simple TTL cache to avoid duplicate LLM calls within a short window."""

    def __init__(self, ttl: int = _CACHE_TTL) -> None:
        self._ttl = ttl
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        ts, value = entry
        if time.monotonic() - ts > self._ttl:
            del self._store[key]
            return None
        return value

    def put(self, key: str, value: Any) -> None:
        self._store[key] = (time.monotonic(), value)


# ── Data Classes ───────────────────────────────────────────

@dataclass
class Signal:
    """A single trading signal."""

    token: str
    action: str  # buy, sell, hold
    confidence: float
    timeframe: str  # 1h, 4h, 1d
    reasoning: str
    whale_supporting: list[str] = field(default_factory=list)


@dataclass
class SignalReport:
    """Complete signal report from the AI engine."""

    signals: list[Signal] = field(default_factory=list)
    overall_sentiment: str = "neutral"
    risk_level: str = "medium"
    raw_response: dict = field(default_factory=dict)


# ── JSON Parsing Helpers ───────────────────────────────────

def _extract_json(text: str) -> dict:
    """
    Best-effort JSON extraction from LLM output.

    Handles raw JSON, markdown code blocks, trailing commas, partial responses.
    """
    text = text.strip()

    # Strip markdown code fences
    fence = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL)
    m = fence.search(text)
    if m:
        text = m.group(1).strip()

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fix trailing commas
    fixed = re.sub(r",\s*([}\]])", r"\1", text)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # Extract first JSON object
    brace_start = text.find("{")
    if brace_start != -1:
        depth = 0
        for i in range(brace_start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[brace_start : i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        fixed_c = re.sub(r",\s*([}\]])", r"\1", candidate)
                        try:
                            return json.loads(fixed_c)
                        except json.JSONDecodeError:
                            break

    logger.warning("Could not parse JSON from LLM response, returning empty dict")
    return {}


# ── Retry Helper ───────────────────────────────────────────

def _call_with_retry(client: openai.OpenAI, *, model: str, messages: list, temperature: float, response_format: dict | None = None, max_retries: int = 3) -> str:
    """Call the LLM with exponential backoff."""
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            kwargs: dict[str, Any] = dict(
                model=model,
                messages=messages,
                temperature=temperature,
            )
            if response_format:
                kwargs["response_format"] = response_format
            resp = client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or "{}"
        except (openai.APIError, openai.APITimeoutError, openai.APIConnectionError) as exc:
            last_exc = exc
            wait = 2 ** attempt
            logger.warning("LLM call attempt %d/%d failed (%s), retrying in %ds", attempt + 1, max_retries, exc, wait)
            time.sleep(wait)
        except Exception as exc:
            last_exc = exc
            logger.error("Non-retryable LLM error: %s", exc)
            break
    raise last_exc or RuntimeError("LLM call failed after retries")


# ── Rule-Based Fallback ────────────────────────────────────

def _momentum_signals(
    whale_events: list[dict[str, Any]],
    dex_swaps: list[dict[str, Any]],
    mnt_price: float = 0.0,
) -> SignalReport:
    """
    Simple momentum-based signal generator when no LLM is configured.

    Heuristics:
    - If >60% of swap volume is buying MNT → BUY signal
    - If >60% of swap volume is selling MNT → SELL signal
    - Otherwise → HOLD
    """
    buy_volume = 0.0
    sell_volume = 0.0

    for swap in dex_swaps:
        token_in = (swap.get("token_in_symbol") or swap.get("tokenIn") or "").upper()
        value_usd = float(swap.get("value_usd") or swap.get("amount_usd") or 0)

        if "MNT" in token_in:
            sell_volume += value_usd
        elif "MNT" in (swap.get("token_out_symbol") or swap.get("tokenOut") or "").upper():
            buy_volume += value_usd
        # Also check for WETH→MNT or USDC→MNT patterns
        elif any(t in token_in for t in ("USDC", "USDT", "DAI")):
            buy_volume += value_usd * 0.5  # assume half could be MNT buys
        elif "WETH" in token_in:
            buy_volume += value_usd * 0.3

    total = buy_volume + sell_volume
    signals: list[Signal] = []

    if total > 0:
        buy_ratio = buy_volume / total
        if buy_ratio > 0.6:
            signals.append(
                Signal(
                    token="MNT",
                    action="buy",
                    confidence=min(0.5 + buy_ratio * 0.3, 0.8),
                    timeframe="1h",
                    reasoning=f"Momentum: {buy_ratio:.0%} of swap volume buying MNT (${buy_volume:,.0f} buy vs ${sell_volume:,.0f} sell).",
                )
            )
        elif buy_ratio < 0.4:
            signals.append(
                Signal(
                    token="MNT",
                    action="sell",
                    confidence=min(0.5 + (1 - buy_ratio) * 0.3, 0.8),
                    timeframe="1h",
                    reasoning=f"Momentum: {1 - buy_ratio:.0%} of swap volume selling MNT (${sell_volume:,.0f} sell vs ${buy_volume:,.0f} buy).",
                )
            )
        else:
            signals.append(
                Signal(
                    token="MNT",
                    action="hold",
                    confidence=0.4,
                    timeframe="1h",
                    reasoning=f"Balanced flow: ${buy_volume:,.0f} buy vs ${sell_volume:,.0f} sell. No clear momentum.",
                )
            )

    sentiment = "neutral"
    risk = "medium"
    if signals:
        if signals[0].action == "buy":
            sentiment = "bullish"
        elif signals[0].action == "sell":
            sentiment = "bearish"

    return SignalReport(
        signals=signals,
        overall_sentiment=sentiment,
        risk_level=risk,
        raw_response={"fallback": True, "buy_volume": buy_volume, "sell_volume": sell_volume},
    )


# ── Main Generator ─────────────────────────────────────────

class SignalGenerator:
    """
    LLM-powered signal generator with provider-agnostic client.

    Features:
    - Works with any OpenAI-compatible endpoint
    - Retry with exponential backoff
    - Robust JSON parsing
    - 30-second result cache
    - Momentum-based fallback when no LLM key is configured
    """

    def __init__(self, api_key: str | None = None, model: str | None = None, base_url: str | None = None) -> None:
        # Resolve credentials: explicit arg > config llm_* > config openai_*
        self.api_key = api_key or settings.llm_api_key or settings.openai_api_key
        self.model = model or settings.llm_model or settings.openai_model
        self.base_url = base_url or settings.llm_base_url or None

        if self.api_key:
            client_kwargs: dict[str, Any] = {"api_key": self.api_key}
            if self.base_url:
                client_kwargs["base_url"] = self.base_url
            self.client = openai.OpenAI(**client_kwargs)
        else:
            self.client = None

        self._cache = _ResultCache()

    def generate(
        self,
        whale_events: list[dict[str, Any]],
        dex_swaps: list[dict[str, Any]],
        mnt_price: float = 0.0,
        time_window_min: int = 5,
    ) -> SignalReport:
        """
        Generate trading signals from whale and DEX data.

        Falls back to momentum-based heuristics when no LLM is configured.
        Caches results for 30 seconds.
        """
        # ── Cache lookup ──
        cache_key = f"{len(whale_events)}:{len(dex_swaps)}:{time_window_min}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug("Returning cached signal report for key %s", cache_key)
            return cached

        # ── Fallback: momentum-based ──
        if not self.client:
            logger.info("No LLM configured — using momentum-based signal generation")
            report = _momentum_signals(whale_events, dex_swaps, mnt_price)
            self._cache.put(cache_key, report)
            return report

        # ── LLM path ──
        events_json = json.dumps(whale_events[:30], indent=2, default=str)
        swaps_json = json.dumps(dex_swaps[:30], indent=2, default=str)

        user_prompt = prompts.SIGNAL_GENERATION_USER.format(
            events_json=events_json,
            swaps_json=swaps_json,
            mnt_price=mnt_price,
            num_events=len(whale_events),
            time_window_min=time_window_min,
        )

        try:
            content = _call_with_retry(
                self.client,
                model=self.model,
                messages=[
                    {"role": "system", "content": prompts.SIGNAL_GENERATION_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                response_format={"type": "json_object"},
            )

            data = _extract_json(content)
            report = self._parse_report(data)
            self._cache.put(cache_key, report)
            return report

        except Exception as e:
            logger.error("LLM signal generation failed after retries: %s", e)
            logger.info("Falling back to momentum-based signals")
            report = _momentum_signals(whale_events, dex_swaps, mnt_price)
            self._cache.put(cache_key, report)
            return report

    @staticmethod
    def _parse_report(data: dict) -> SignalReport:
        """Parse raw LLM JSON into a SignalReport."""
        signals = []
        for s in data.get("signals", []):
            signals.append(
                Signal(
                    token=s.get("token", "UNKNOWN"),
                    action=s.get("action", "hold"),
                    confidence=s.get("confidence", 0.0),
                    timeframe=s.get("timeframe", "1h"),
                    reasoning=s.get("reasoning", ""),
                    whale_supporting=s.get("whale_supporting", []),
                )
            )

        return SignalReport(
            signals=signals,
            overall_sentiment=data.get("overall_sentiment", "neutral"),
            risk_level=data.get("risk_level", "medium"),
            raw_response=data,
        )
