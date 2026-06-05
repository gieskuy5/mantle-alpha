"""
Signal generator for Mantle Alpha.

Generates buy/sell/hold trading signals from whale activity data
and DEX swap patterns using LLM analysis.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import openai

from config import settings
from ai import prompts

logger = logging.getLogger(__name__)


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


class SignalGenerator:
    """
    LLM-powered signal generator.

    Combines whale wallet events and DEX swap data to produce
    actionable trading signals with confidence scores.
    """

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or settings.openai_api_key
        self.model = model or settings.openai_model
        self.client = openai.OpenAI(api_key=self.api_key) if self.api_key else None

    def generate(
        self,
        whale_events: list[dict[str, Any]],
        dex_swaps: list[dict[str, Any]],
        mnt_price: float = 0.0,
        time_window_min: int = 5,
    ) -> SignalReport:
        """
        Generate trading signals from whale and DEX data.

        Args:
            whale_events: Recent whale wallet events.
            dex_swaps: Recent DEX swap events.
            mnt_price: Current MNT price in USD.
            time_window_min: Analysis time window in minutes.

        Returns:
            SignalReport with generated signals.
        """
        if not self.client:
            logger.warning("No OpenAI API key configured — returning empty signals")
            return SignalReport()

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
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": prompts.SIGNAL_GENERATION_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content or "{}"
            data = json.loads(content)
            return self._parse_report(data)

        except openai.APIError as e:
            logger.error("OpenAI API error: %s", e)
            return SignalReport()
        except json.JSONDecodeError as e:
            logger.error("Failed to parse LLM response: %s", e)
            return SignalReport()
        except Exception:
            logger.exception("Unexpected error in signal generation")
            return SignalReport()

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
