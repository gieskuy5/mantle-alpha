"""
DEX swap monitor for Mantle Alpha.

Indexes swap events on Merchant Moe, Agni Finance, and Fluxion
to track smart money flow across DEXes on Mantle Network.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from web3 import Web3

from config import settings
from indexer.mantle_client import MantleClient

logger = logging.getLogger(__name__)

# ── Common Uniswap V2–style Swap event signature ─────────
# event Swap(address indexed sender, uint256 amount0In, uint256 amount1In,
#            uint256 amount0Out, uint256 amount1Out, address indexed to)
SWAP_TOPIC_V2 = Web3.keccak(text="Swap(address,uint256,uint256,uint256,uint256,address)").hex()

# Uniswap V3–style Swap event
SWAP_TOPIC_V3 = Web3.keccak(
    text="Swap(address indexed sender, address indexed recipient, int256 amount0, "
         "int256 amount1, uint160 sqrtPriceX96, uint128 liquidity, int24 tick)"
).hex()


@dataclass
class SwapEvent:
    """Represents a DEX swap detected on-chain."""

    dex: str  # "merchant_moe", "agni_finance", "fluxion"
    tx_hash: str
    block_number: int
    log_index: int
    sender: str
    to: str
    amount_in: int
    amount_out: int
    pair_address: str
    raw_log: dict = field(default_factory=dict)


class DexMonitor:
    """
    Monitors DEX swap activity on Mantle Network.

    Listens for Swap events on configured DEX router/factory contracts
    and normalizes them into SwapEvent objects.
    """

    # DEX name → router/factory contract address
    DEX_CONTRACTS: dict[str, str] = {
        "merchant_moe": settings.merchant_moe_router,
        "agni_finance": settings.agni_finance_router,
        "fluxion": settings.fluxion_router,
    }

    def __init__(self, client: MantleClient | None = None) -> None:
        self.client = client or MantleClient()
        self._seen_txs: set[str] = set()

    # ── Public API ──────────────────────────────────────────

    def get_swaps_in_block(self, block_number: int) -> list[SwapEvent]:
        """
        Query all Swap events emitted in a given block from tracked DEXes.
        Returns a list of normalized SwapEvent objects.
        """
        events: list[SwapEvent] = []

        for dex_name, contract_addr in self.DEX_CONTRACTS.items():
            if contract_addr == "0x0000000000000000000000000000000000000000":
                continue  # Skip unconfigured contracts

            try:
                logs = self.client.get_logs(
                    {
                        "fromBlock": block_number,
                        "toBlock": block_number,
                        "address": Web3.to_checksum_address(contract_addr),
                        "topics": [[SWAP_TOPIC_V2, SWAP_TOPIC_V3]],
                    }
                )

                for log in logs:
                    swap = self._parse_log(dex_name, log, block_number)
                    if swap:
                        events.append(swap)

            except Exception:
                logger.exception(
                    "Error fetching %s logs for block %d", dex_name, block_number
                )

        logger.debug("Block %d: found %d swap events", block_number, len(events))
        return events

    def get_swaps_for_wallet(
        self, wallet_address: str, from_block: int, to_block: int
    ) -> list[SwapEvent]:
        """Fetch all swap events involving a specific wallet address."""
        events: list[SwapEvent] = []
        addr_topic = "0x" + "0" * 24 + wallet_address[2:].lower()

        for dex_name, contract_addr in self.DEX_CONTRACTS.items():
            if contract_addr == "0x0000000000000000000000000000000000000000":
                continue

            try:
                # Filter by sender (topic[1])
                logs = self.client.get_logs(
                    {
                        "fromBlock": from_block,
                        "toBlock": to_block,
                        "address": Web3.to_checksum_address(contract_addr),
                        "topics": [[SWAP_TOPIC_V2, SWAP_TOPIC_V3], [addr_topic]],
                    }
                )
                for log in logs:
                    swap = self._parse_log(dex_name, log, log.get("blockNumber", 0))
                    if swap:
                        events.append(swap)

            except Exception:
                logger.exception("Error querying %s for wallet %s", dex_name, wallet_address)

        return events

    # ── Internals ───────────────────────────────────────────

    def _parse_log(self, dex_name: str, log: dict, block_number: int) -> SwapEvent | None:
        """Parse a raw log into a SwapEvent."""
        try:
            topics = log.get("topics", [])
            data = log.get("data", "0x")
            tx_hash = log.get("transactionHash", b"").hex() if isinstance(log.get("transactionHash"), bytes) else log.get("transactionHash", "")
            log_index = log.get("logIndex", 0)

            if not topics:
                return None

            event_sig = topics[0].hex() if isinstance(topics[0], bytes) else topics[0]

            if event_sig == SWAP_TOPIC_V2:
                return self._parse_v2_swap(dex_name, log, tx_hash, log_index, block_number)
            elif event_sig == SWAP_TOPIC_V3:
                return self._parse_v3_swap(dex_name, log, tx_hash, log_index, block_number)
            else:
                return None

        except Exception:
            logger.exception("Failed to parse swap log from %s", dex_name)
            return None

    @staticmethod
    def _parse_v2_swap(
        dex_name: str, log: dict, tx_hash: str, log_index: int, block_number: int
    ) -> SwapEvent | None:
        """Parse a Uniswap V2–style Swap event."""
        topics = log.get("topics", [])
        data = log.get("data", b"0x")
        if isinstance(data, bytes):
            data = data.hex()

        sender = "0x" + topics[1][-40:] if len(topics) > 1 else ""
        to = "0x" + topics[2][-40:] if len(topics) > 2 else ""

        # Decode uint256 amounts from data (4 x 32 bytes)
        decoded = Web3.to_bytes(hexstr=data)
        if len(decoded) >= 128:
            amount0_in = int.from_bytes(decoded[0:32], "big")
            amount1_in = int.from_bytes(decoded[32:64], "big")
            amount0_out = int.from_bytes(decoded[64:96], "big")
            amount1_out = int.from_bytes(decoded[96:128], "big")
        else:
            amount0_in = amount1_in = amount0_out = amount1_out = 0

        amount_in = amount0_in or amount1_in
        amount_out = amount0_out or amount1_out

        return SwapEvent(
            dex=dex_name,
            tx_hash=tx_hash,
            block_number=block_number,
            log_index=log_index,
            sender=sender,
            to=to,
            amount_in=amount_in,
            amount_out=amount_out,
            pair_address=log.get("address", ""),
            raw_log=dict(log),
        )

    @staticmethod
    def _parse_v3_swap(
        dex_name: str, log: dict, tx_hash: str, log_index: int, block_number: int
    ) -> SwapEvent | None:
        """Parse a Uniswap V3–style Swap event."""
        topics = log.get("topics", [])
        data = log.get("data", b"0x")
        if isinstance(data, bytes):
            data = data.hex()

        sender = "0x" + topics[1][-40:] if len(topics) > 1 else ""
        to = "0x" + topics[2][-40:] if len(topics) > 2 else ""

        decoded = Web3.to_bytes(hexstr=data)
        if len(decoded) >= 64:
            amount0 = int.from_bytes(decoded[0:32], "big", signed=True)
            amount1 = int.from_bytes(decoded[32:64], "big", signed=True)
        else:
            amount0 = amount1 = 0

        amount_in = abs(amount0) if amount0 > 0 else abs(amount1)
        amount_out = abs(amount1) if amount0 > 0 else abs(amount0)

        return SwapEvent(
            dex=dex_name,
            tx_hash=tx_hash,
            block_number=block_number,
            log_index=log_index,
            sender=sender,
            to=to,
            amount_in=amount_in,
            amount_out=amount_out,
            pair_address=log.get("address", ""),
            raw_log=dict(log),
        )
