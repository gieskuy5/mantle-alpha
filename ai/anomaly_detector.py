"""
LLM-based anomaly detector for Mantle Alpha.

Uses an LLM (any OpenAI-compatible provider) to analyze batches of whale
events and DEX swaps for unusual patterns that may signal alpha.

Falls back to a rule-based detector when no LLM is configured.
Caches results for 30 seconds to avoid duplicate API calls.
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


# ── JSON Parsing Helpers ───────────────────────────────────

def _extract_json(text: str) -> dict:
    """
    Best-effort JSON extraction from LLM output.

    Handles:
    - Raw JSON
    - Markdown code blocks (```json ... ```)
    - Partial / trailing commas
    """
    text = text.strip()

    # Strip markdown code fences
    fence = re.compile(r"```(?:json)?\s*\n?(.*?)```", re.DOTALL)
    m = fence.search(text)
    if m:
        text = m.group(1).strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try fixing trailing commas
    fixed = re.sub(r",\s*([}\]])", r"\1", text)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # Try extracting the first JSON object
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
                        # Try trailing-comma fix on the candidate
                        fixed_c = re.sub(r",\s*([}\]])", r"\1", candidate)
                        try:
                            return json.loads(fixed_c)
                        except json.JSONDecodeError:
                            break

    logger.warning("Could not parse JSON from LLM response, returning empty dict")
    return {}


# ── Retry Helper ───────────────────────────────────────────

def _call_with_retry(client: openai.OpenAI, *, model: str, messages: list, temperature: float, response_format: dict | None = None, max_retries: int = 3) -> str:
    """Call the LLM with exponential backoff (max_retries attempts)."""
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

def _rule_based_detect(events: list[dict[str, Any]]) -> AnomalyReport:
    """
    Simple threshold-based fallback when no LLM is configured.

    Flags:
    - Balance changes > 20%
    - Large swaps > $50,000
    """
    anomalies: list[Anomaly] = []

    for ev in events:
        ev_type = ev.get("type", "").lower()
        value_usd = float(ev.get("value_usd") or ev.get("amount_usd") or 0)
        wallet = ev.get("wallet") or ev.get("from") or ev.get("address") or "unknown"

        # Large swap detection
        if "swap" in ev_type and value_usd > 50_000:
            anomalies.append(
                Anomaly(
                    wallet=str(wallet),
                    type="unusual_size",
                    severity="high" if value_usd > 200_000 else "medium",
                    description=f"Large swap of ${value_usd:,.0f} detected.",
                    suggested_action="watch",
                )
            )

        # Balance change detection (> 20%)
        old_bal = float(ev.get("old_balance") or ev.get("previous_balance") or 0)
        new_bal = float(ev.get("new_balance") or ev.get("balance") or 0)
        if old_bal > 0 and new_bal > 0:
            pct_change = abs(new_bal - old_bal) / old_bal
            if pct_change > 0.20:
                direction = "increased" if new_bal > old_bal else "decreased"
                anomalies.append(
                    Anomaly(
                        wallet=str(wallet),
                        type="accumulation" if new_bal > old_bal else "distribution",
                        severity="high" if pct_change > 0.50 else "medium",
                        description=f"Balance {direction} by {pct_change:.0%} (${old_bal:,.0f} → ${new_bal:,.0f}).",
                        suggested_action="watch",
                    )
                )

    return AnomalyReport(
        anomalies_detected=len(anomalies) > 0,
        confidence=0.5,
        summary=f"Rule-based fallback: {len(anomalies)} anomaly/anomalies flagged (threshold check).",
        anomalies=anomalies,
        market_sentiment="neutral",
        raw_response={"fallback": True},
    )


# ── Main Detector ──────────────────────────────────────────

class AnomalyDetector:
    """
    LLM-powered anomaly detector with provider-agnostic client.

    Features:
    - Works with any OpenAI-compatible endpoint (OpenAI, Xiaomi/9router, local, etc.)
    - Retry with exponential backoff
    - Robust JSON parsing
    - 30-second result cache
    - Rule-based fallback when no LLM key is configured
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

    def detect(
        self,
        events: list[dict[str, Any]],
        from_block: int = 0,
        to_block: int = 0,
        time_window_min: int = 5,
    ) -> AnomalyReport:
        """
        Analyze whale events for anomalies.

        Falls back to rule-based detection when no LLM is configured.
        Caches results for 30 seconds to avoid duplicate API calls.
        """
        # ── Cache lookup ──
        cache_key = f"{from_block}:{to_block}:{len(events)}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug("Returning cached anomaly report for key %s", cache_key)
            return cached

        # ── Fallback: rule-based ──
        if not self.client:
            logger.info("No LLM configured — using rule-based anomaly detection")
            report = _rule_based_detect(events)
            self._cache.put(cache_key, report)
            return report

        # ── LLM path ──
        events_json = json.dumps(events[:50], indent=2, default=str)  # Cap at 50 events

        user_prompt = prompts.ANOMALY_DETECTION_USER.format(
            events_json=events_json,
            from_block=from_block,
            to_block=to_block,
            time_window_min=time_window_min,
        )

        try:
            content = _call_with_retry(
                self.client,
                model=self.model,
                messages=[
                    {"role": "system", "content": prompts.ANOMALY_DETECTION_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
            )

            data = _extract_json(content)
            report = self._parse_report(data)
            self._cache.put(cache_key, report)
            return report

        except Exception as e:
            logger.error("LLM anomaly detection failed after retries: %s", e)
            logger.info("Falling back to rule-based detection")
            report = _rule_based_detect(events)
            self._cache.put(cache_key, report)
            return report

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
