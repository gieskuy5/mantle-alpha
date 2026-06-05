"""
Basic tests for Mantle Alpha.

Run with: python -m pytest tests/ -v
"""

import pytest


def test_config_import():
    """Verify config module can be imported."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from config import settings
    assert settings.mantle_chain_id == 5000


def test_mantle_client_creation():
    """Verify MantleClient can be instantiated."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from indexer.mantle_client import MantleClient
    client = MantleClient(rpc_url="https://rpc.mantle.xyz")
    assert client.rpc_url == "https://rpc.mantle.xyz"


def test_wallet_tracker_init():
    """Verify WalletTracker initializes correctly."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from indexer.wallet_tracker import WalletTracker
    tracker = WalletTracker(
        whale_addresses=["0x1234567890abcdef1234567890abcdef12345678"],
        threshold_mnt=5000.0,
    )
    assert len(tracker.whale_addresses) == 1
    assert tracker.threshold_mnt == 5000.0


def test_anomaly_detector_init():
    """Verify AnomalyDetector can be created without API key."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from ai.anomaly_detector import AnomalyDetector
    detector = AnomalyDetector(api_key="")
    assert detector.client is None


def test_signal_generator_init():
    """Verify SignalGenerator can be created without API key."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from ai.signal_generator import SignalGenerator
    gen = SignalGenerator(api_key="")
    assert gen.client is None


def test_anomaly_report_dataclass():
    """Verify AnomalyReport dataclass works."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from ai.anomaly_detector import AnomalyReport
    report = AnomalyReport(
        anomalies_detected=False,
        confidence=0.0,
        summary="Test",
    )
    assert report.summary == "Test"
    assert report.anomalies == []


def test_signal_report_dataclass():
    """Verify SignalReport dataclass works."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from ai.signal_generator import SignalReport
    report = SignalReport()
    assert report.overall_sentiment == "neutral"
    assert report.risk_level == "medium"


def test_prompts_exist():
    """Verify prompt templates are defined."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from ai import prompts
    assert len(prompts.ANOMALY_DETECTION_SYSTEM) > 0
    assert len(prompts.ANOMALY_DETECTION_USER) > 0
    assert len(prompts.SIGNAL_GENERATION_SYSTEM) > 0
    assert len(prompts.SIGNAL_GENERATION_USER) > 0
    assert len(prompts.WALLET_CLASSIFICATION_SYSTEM) > 0
    assert len(prompts.WALLET_CLASSIFICATION_USER) > 0


def test_dex_monitor_init():
    """Verify DexMonitor can be instantiated."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from indexer.dex_monitor import DexMonitor
    monitor = DexMonitor()
    assert "merchant_moe" in monitor.DEX_CONTRACTS
    assert "agni_finance" in monitor.DEX_CONTRACTS
    assert "fluxion" in monitor.DEX_CONTRACTS


def test_telegram_bot_init():
    """Verify TelegramBot can be instantiated."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from alerts.telegram_bot import TelegramBot
    bot = TelegramBot(token="test", chat_id="123")
    assert bot.token == "test"
    assert bot.chat_id == "123"
