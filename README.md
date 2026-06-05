# 🧠 Mantle Alpha — AI-Powered Smart Money Tracker

> **Mantle Turing Test Hackathon 2026 — Track 2: AI Alpha & Data**

Mantle Alpha is an intelligent on-chain analytics platform that tracks whale wallets, monitors DEX activity, and generates AI-powered trading signals on the **Mantle Network**. It combines real-time blockchain indexing with LLM-based anomaly detection to surface actionable alpha before the market catches on.

---

## 🏆 Hackathon Info

- **Event:** Mantle Turing Test Hackathon 2026
- **Track:** Track 2 — AI Alpha & Data
- **Deadline:** June 15, 2026
- **Network:** Mantle Network (Chain ID: 5000)

---

## ✨ Features

- 🐋 **Whale Wallet Tracking** — Monitor top wallets on Mantle in real-time
- 📊 **DEX Swap Monitoring** — Track swaps across Merchant Moe, Agni Finance, and Fluxion
- 🤖 **AI Anomaly Detection** — LLM-powered analysis of transaction patterns to detect unusual activity
- 📈 **Signal Generation** — Automated buy/sell/hold signals derived from whale behavior
- 🔔 **Telegram Alerts** — Instant notifications when smart money moves
- 🖥️ **Live Dashboard** — FastAPI-powered web interface with real-time data

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Mantle Alpha                              │
├─────────────┬──────────────┬──────────────┬─────────────────────┤
│             │              │              │                     │
│  ┌──────────▼──────────┐  │  ┌───────────▼───────────┐         │
│  │   Mantle RPC Node   │  │  │   DEX Contracts       │         │
│  │  (web3.py client)   │  │  │  Merchant Moe         │         │
│  └──────────┬──────────┘  │  │  Agni Finance         │         │
│             │              │  │  Fluxion              │         │
│             ▼              │  └───────────┬───────────┘         │
│  ┌──────────────────┐     │              │                      │
│  │  Wallet Tracker   │◄────┘              ▼                      │
│  │  (Whale Monitor)  │     ┌──────────────────────┐             │
│  └──────────┬───────┘     │    DEX Monitor        │             │
│             │              │  (Swap Indexer)       │             │
│             │              └───────────┬───────────┘             │
│             ▼                          ▼                         │
│  ┌─────────────────────────────────────────────┐                │
│  │              AI Engine                       │                │
│  │  ┌─────────────────┐ ┌───────────────────┐  │                │
│  │  │ Anomaly Detector │ │ Signal Generator  │  │                │
│  │  │  (LLM-powered)   │ │ (Buy/Sell/Hold)   │  │                │
│  │  └─────────────────┘ └───────────────────┘  │                │
│  └──────────────────────┬──────────────────────┘                │
│                         │                                        │
│             ┌───────────┼───────────┐                           │
│             ▼           ▼           ▼                           │
│  ┌──────────────┐ ┌──────────┐ ┌──────────────┐                │
│  │  Telegram Bot │ │ Dashboard│ │   REST API   │                │
│  │   (Alerts)    │ │ (FastAPI)│ │  (FastAPI)   │                │
│  └──────────────┘ └──────────┘ └──────────────┘                │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🛠️ Tech Stack

| Component        | Technology                        |
|------------------|-----------------------------------|
| Language         | Python 3.11+                      |
| Blockchain       | web3.py + Mantle Network RPC      |
| Web Framework    | FastAPI + Jinja2 + Uvicorn        |
| AI/LLM           | OpenAI API / Anthropic Claude     |
| Messaging        | Telegram Bot API                  |
| DEXes Tracked    | Merchant Moe, Agni Finance, Fluxion |
| Templating       | Jinja2                            |

---

## 📁 Project Structure

```
mantle-alpha/
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── config.py                  # Configurable RPC endpoints, API keys, thresholds
├── indexer/
│   ├── __init__.py
│   ├── wallet_tracker.py      # Whale wallet monitoring
│   ├── dex_monitor.py         # DEX swap indexer
│   └── mantle_client.py       # Mantle RPC client (web3.py)
├── ai/
│   ├── __init__.py
│   ├── anomaly_detector.py    # LLM-based anomaly detection
│   ├── signal_generator.py    # Buy/sell/hold signal generation
│   └── prompts.py             # Prompt templates for LLM analysis
├── alerts/
│   ├── __init__.py
│   └── telegram_bot.py        # Telegram alert bot
├── dashboard/
│   ├── __init__.py
│   ├── app.py                 # FastAPI backend
│   ├── static/                # CSS / JS assets
│   └── templates/             # Jinja2 HTML templates
├── scripts/
│   ├── run_indexer.py         # Main indexer loop
│   ├── run_dashboard.py       # Start dashboard server
│   └── run_bot.py             # Start Telegram bot
└── tests/
    └── test_basic.py
```

---

## 🚀 Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/gieskuy5/mantle-alpha.git
cd mantle-alpha
```

### 2. Install Dependencies

```bash
python -m venv venv
source venv/bin/activate   # Linux/Mac
pip install -r requirements.txt
```

### 3. Configure Environment

```bash
cp .env.example .env
# Edit .env with your API keys
```

### 4. Run the Indexer

```bash
python scripts/run_indexer.py
```

### 5. Start the Dashboard

```bash
python scripts/run_dashboard.py
# Open http://localhost:8000
```

### 6. Start the Telegram Bot

```bash
python scripts/run_bot.py
```

---

## ⚙️ Configuration

All configuration is centralized in `config.py` and can be overridden via environment variables:

| Variable                | Description                          | Default                    |
|------------------------|--------------------------------------|----------------------------|
| `MANTLE_RPC_URL`       | Mantle Network RPC endpoint          | `https://rpc.mantle.xyz`   |
| `OPENAI_API_KEY`       | OpenAI API key for LLM analysis      | —                          |
| `TELEGRAM_BOT_TOKEN`   | Telegram bot token                   | —                          |
| `TELEGRAM_CHAT_ID`     | Chat ID for alerts                   | —                          |
| `WHALE_THRESHOLD_MNT`  | Min MNT balance to track as whale    | `10000`                    |
| `POLL_INTERVAL_SEC`    | Block polling interval               | `5`                        |

---

## 🧪 Testing

```bash
python -m pytest tests/ -v
```

---

## 📄 License

MIT License — Built for the Mantle Turing Test Hackathon 2026.

---

<p align="center">
  <b>Built with 🧠 for the Mantle Turing Test Hackathon 2026</b><br>
  <sub>Track 2: AI Alpha & Data</sub>
</p>
