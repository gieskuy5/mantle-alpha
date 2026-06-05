"""
Whale wallet tracker for Mantle Alpha.

Monitors a set of high-value wallets for balance changes and outgoing
transactions, feeding data to the AI engine for signal generation.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Generator

from config import settings
from indexer.mantle_client import MantleClient

logger = logging.getLogger(__name__)


@dataclass
class WalletSnapshot:
    """Point-in-time snapshot of a wallet's state."""

    address: str
    balance_mnt: float
    block_number: int
    timestamp: float = field(default_factory=time.time)


@dataclass
class WhaleEvent:
    """Represents a meaningful whale activity event."""

    address: str
    event_type: str  # "balance_change", "large_transfer", "new_activity"
    amount_mnt: float
    block_number: int
    details: dict = field(default_factory=dict)


class WalletTracker:
    """
    Tracks whale wallets on Mantle Network.

    Polls balances at each new block and emits WhaleEvent objects
    when significant changes are detected.
    """

    def __init__(
        self,
        client: MantleClient | None = None,
        whale_addresses: list[str] | None = None,
        threshold_mnt: float | None = None,
    ) -> None:
        self.client = client or MantleClient()
        self.whale_addresses = whale_addresses or settings.whale_wallets
        self.threshold_mnt = threshold_mnt or settings.whale_threshold_mnt
        self._snapshots: dict[str, WalletSnapshot] = {}

    # ── Public API ──────────────────────────────────────────

    def add_wallet(self, address: str) -> None:
        """Start tracking a new wallet."""
        if address not in self.whale_addresses:
            self.whale_addresses.append(address)
            logger.info("Now tracking wallet %s", address)

    def remove_wallet(self, address: str) -> None:
        """Stop tracking a wallet."""
        if address in self.whale_addresses:
            self.whale_addresses.remove(address)
            self._snapshots.pop(address, None)
            logger.info("Stopped tracking wallet %s", address)

    def poll(self) -> list[WhaleEvent]:
        """
        Poll all tracked wallets and return any detected events.
        Should be called once per new block.
        """
        if not self.whale_addresses:
            return []

        block_number = self.client.latest_block()
        events: list[WhaleEvent] = []

        for addr in self.whale_addresses:
            try:
                balance = self.client.get_balance_mnt(addr)
                snapshot = WalletSnapshot(
                    address=addr, balance_mnt=balance, block_number=block_number
                )

                prev = self._snapshots.get(addr)
                if prev is not None:
                    delta = snapshot.balance_mnt - prev.balance_mnt
                    if abs(delta) >= self.threshold_mnt * 0.05:  # 5% threshold change
                        event_type = (
                            "balance_increase" if delta > 0 else "balance_decrease"
                        )
                        events.append(
                            WhaleEvent(
                                address=addr,
                                event_type=event_type,
                                amount_mnt=delta,
                                block_number=block_number,
                                details={
                                    "previous_balance": prev.balance_mnt,
                                    "new_balance": snapshot.balance_mnt,
                                    "delta_pct": (
                                        (delta / prev.balance_mnt * 100)
                                        if prev.balance_mnt
                                        else 0
                                    ),
                                },
                            )
                        )
                        logger.info(
                            "Whale %s: %s %.4f MNT (block %d)",
                            addr[:10],
                            event_type,
                            abs(delta),
                            block_number,
                        )

                self._snapshots[addr] = snapshot

            except Exception:
                logger.exception("Error polling wallet %s", addr)

        return events

    def get_snapshot(self, address: str) -> WalletSnapshot | None:
        """Return the latest snapshot for a wallet, or None."""
        return self._snapshots.get(address)

    def iter_blocks(self) -> Generator[tuple[int, list[WhaleEvent]], None, None]:
        """
        Generator that yields (block_number, events) for each new block.
        Useful for running the main indexer loop.
        """
        last_block = self.client.latest_block()
        while True:
            current = self.client.latest_block()
            if current > last_block:
                events = self.poll()
                yield current, events
                last_block = current
            time.sleep(settings.poll_interval_sec)
