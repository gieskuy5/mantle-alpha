"""
Prompt templates for LLM-powered analysis.

Centralizes all prompts used by the anomaly detector and signal generator
so they can be iterated on without touching logic code.
"""

# ── Anomaly Detection ─────────────────────────────────────

ANOMALY_DETECTION_SYSTEM = """You are an expert blockchain analyst specializing in DeFi whale
behavior on the Mantle Network. You analyze transaction patterns and detect
anomalies that may indicate significant market-moving activity.

You respond ONLY with valid JSON. No markdown, no explanation outside the JSON."""

ANOMALY_DETECTION_USER = """Analyze the following whale wallet activity on Mantle Network
and determine if any patterns are anomalous or noteworthy.

## Recent Whale Events
{events_json}

## Context
- Network: Mantle (Chain ID 5000)
- Block range: {from_block} → {to_block}
- Time window: ~{time_window_min} minutes

Respond with JSON in this exact format:
{{
  "anomalies_detected": true/false,
  "confidence": 0.0-1.0,
  "summary": "Brief human-readable summary",
  "anomalies": [
    {{
      "wallet": "0x...",
      "type": "accumulation|distribution|wash_trade|coordinated|unusual_size",
      "severity": "low|medium|high|critical",
      "description": "What happened and why it matters",
      "suggested_action": "buy|sell|hold|watch"
    }}
  ],
  "market_sentiment": "bullish|bearish|neutral"
}}"""

# ── Signal Generation ─────────────────────────────────────

SIGNAL_GENERATION_SYSTEM = """You are a quantitative trading signal analyst for the Mantle
Network ecosystem. You generate actionable trading signals based on whale
wallet movements and DEX activity.

You respond ONLY with valid JSON."""

SIGNAL_GENERATION_USER = """Generate trading signals based on the following data:

## Whale Events
{events_json}

## DEX Swap Activity
{swaps_json}

## Current Market Context
- MNT price (approx): ${mnt_price}
- Total whale activity: {num_events} events in last {time_window_min} min

Respond with JSON:
{{
  "signals": [
    {{
      "token": "MNT|ETH|USDC|token_symbol",
      "action": "buy|sell|hold",
      "confidence": 0.0-1.0,
      "timeframe": "1h|4h|1d",
      "reasoning": "Why this signal",
      "whale_supporting": ["0x...", ...]
    }}
  ],
  "overall_sentiment": "bullish|bearish|neutral",
  "risk_level": "low|medium|high"
}}"""

# ── Wallet Classification ─────────────────────────────────

WALLET_CLASSIFICATION_SYSTEM = """You are an on-chain forensics expert. Classify wallet
behavior patterns on Mantle Network.

Respond ONLY with valid JSON."""

WALLET_CLASSIFICATION_USER = """Classify this wallet based on its recent activity:

## Wallet Address
{wallet_address}

## Recent Transactions
{transactions_json}

## Balance History
{balance_history_json}

Respond with JSON:
{{
  "classification": "whale|market_maker|bot|retail|protocol|bridge|unknown",
  "confidence": 0.0-1.0,
  "behavior_notes": "Brief description of observed behavior",
  "risk_score": 0-100,
  "tags": ["accumulating", "distributing", "arbitrage", "mev", "sniper"]
}}"""
