"""
LLM-based anomaly detector for Mantle Alpha.

Uses an LLM (OpenAI GPT-4o-mini by default) to analyze batches of whale
events and DEX swaps for unusual patterns that may signal alpha.
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
class Anomaly:
    """A single detected anomaly."""

    wallet: str
    type: str  # accumulation, distribution, wash_trade, coordinated, unusual_size
    severity: str  # low, medium, high, critical
    description: str
    suggested_action: str  # buy, sell, hold, watch


@dataclass
class AnomalyReport:
    """Complete anomaly detection report from the AI engine."""

    anomalies_detected: bool
    confidence: float
    summary: str
    anomalies: list[Anomaly] = field(default_factory=list)
    market_sentiment: str = "neutral"
    raw_response: dict = field(default_factory=dict)


class AnomalyDetector:
    """
    LLM-powered anomaly detector.

    Sends batches of whale events and DEX swap data to an LLM
    for pattern analysis and anomaly detection.
    """

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        self.api_key = api_key or settings.openai_api_key
        self.model = model or settings.openai_model
        self.client = openai.OpenAI(api_key=self.api_key) if self.api_key else None

    def detect(
        self,
        events: list[dict[str, Any]],
        from_block: int = 0,
        to_block: int = 0,
        time_window_min: int = 5,
    ) -> AnomalyReport:
        """
        Analyze whale events for anomalies.

        Args:
            events: List of whale event dicts (from WalletTracker).
            from_block: Starting block number of the analysis window.
            to_block: Ending block number.
            time_window_min: Approximate time window in minutes.

        Returns:
            AnomalyReport with detected anomalies and sentiment.
        """
        if not self.client:
            logger.warning("No OpenAI API key configured — returning empty report")
            return AnomalyReport(
                anomalies_detected=False,
                confidence=0.0,
                summary="AI engine not configured (missing API key)",
            )

        events_json = json.dumps(events[:50], indent=2, default=str)  # Cap at 50 events

        user_prompt = prompts.ANOMALY_DETECTION_USER.format(
            events_json=events_json,
            from_block=from_block,
            to_block=to_block,
            time_window_min=time_window_min,
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": prompts.ANOMALY_DETECTION_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
            )

            content = response.choices[0].message.content or "{}"
            data = json.loads(content)
            return self._parse_report(data)

        except openai.APIError as e:
            logger.error("OpenAI API error: %s", e)
            return AnomalyReport(
                anomalies_detected=False, confidence=0.0, summary=f"API error: {e}"
            )
        except json.JSONDecodeError as e:
            logger.error("Failed to parse LLM response: %s", e)
            return AnomalyReport(
                anomalies_detected=False, confidence=0.0, summary="Invalid LLM response"
            )
        except Exception:
            logger.exception("Unexpected error in anomaly detection")
            return AnomalyReport(
                anomalies_detected=False, confidence=0.0, summary="Unexpected error"
            )

    @staticmethod
    def _parse_report(data: dict) -> AnomalyReport:
        """Parse raw LLM JSON into an AnomalyReport."""
        anomalies = []
        for a in data.get("anomalies", []):
            anomalies.append(
                Anomaly(
                    wallet=a.get("wallet", ""),
                    type=a.get("type", "unknown"),
                    severity=a.get("severity", "low"),
                    description=a.get("description", ""),
                    suggested_action=a.get("suggested_action", "watch"),
                )
            )

        return AnomalyReport(
            anomalies_detected=data.get("anomalies_detected", False),
            confidence=data.get("confidence", 0.0),
            summary=data.get("summary", ""),
            anomalies=anomalies,
            market_sentiment=data.get("market_sentiment", "neutral"),
            raw_response=data,
        )
