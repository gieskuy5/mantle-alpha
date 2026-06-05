"""
Mantle Network RPC client using web3.py.

Provides a thin async-friendly wrapper around the Mantle JSON-RPC endpoint
for querying blocks, transactions, balances, and contract state.
"""

from __future__ import annotations

import logging
from typing import Any

from web3 import Web3
from web3.exceptions import BlockNotFound

from config import settings

logger = logging.getLogger(__name__)


class MantleClient:
    """Client for interacting with the Mantle Network via JSON-RPC."""

    def __init__(self, rpc_url: str | None = None) -> None:
        self.rpc_url = rpc_url or settings.mantle_rpc_url
        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
        if not self.w3.is_connected():
            logger.warning("Could not connect to Mantle RPC at %s", self.rpc_url)
        else:
            logger.info("Connected to Mantle RPC — chain ID %s", self.w3.eth.chain_id)

    # ── Helpers ─────────────────────────────────────────────

    def is_connected(self) -> bool:
        return self.w3.is_connected()

    def latest_block(self) -> int:
        return self.w3.eth.block_number

    # ── Queries ─────────────────────────────────────────────

    def get_balance(self, address: str) -> int:
        """Return the MNT balance (in wei) of *address*."""
        return self.w3.eth.get_balance(Web3.to_checksum_address(address))

    def get_balance_mnt(self, address: str) -> float:
        """Return the MNT balance (in ether units) of *address*."""
        wei = self.get_balance(address)
        return float(self.w3.from_wei(wei, "ether"))

    def get_block(self, block_number: int, full_transactions: bool = False) -> Any:
        """Fetch a block by number. Raises *BlockNotFound* on miss."""
        try:
            return self.w3.eth.get_block(block_number, full_transactions=full_transactions)
        except BlockNotFound:
            logger.error("Block %d not found", block_number)
            raise

    def get_transaction(self, tx_hash: str) -> Any:
        """Fetch a transaction by hash."""
        return self.w3.eth.get_transaction(tx_hash)

    def get_transaction_receipt(self, tx_hash: str) -> Any:
        """Fetch a transaction receipt by hash."""
        return self.w3.eth.get_transaction_receipt(tx_hash)

    def get_logs(self, filter_params: dict) -> list[dict]:
        """Query event logs with arbitrary filter parameters."""
        return self.w3.eth.get_logs(filter_params)


# Module-level singleton
client = MantleClient()
