"""
DEX swap monitor for Mantle Alpha.

Indexes swap events across all DEXes on Mantle Network by monitoring
Swap event topics. Works with any Uniswap V2/V3-style DEX automatically.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from web3 import Web3

from config import settings
from indexer.mantle_client import MantleClient

logger = logging.getLogger(__name__)

# ── Swap Event Signatures ─────────────────────────────────
# Uniswap V2-style: Swap(address indexed sender, uint256 amount0In, uint256 amount1In, uint256 amount0Out, uint256 amount1Out, address indexed to)
SWAP_TOPIC_V2 = Web3.keccak(
    text="Swap(address,uint256,uint256,uint256,uint256,address)"
).hex()

# Uniswap V3-style: Swap(address indexed sender, address indexed recipient, int256 amount0, int256 amount1, uint160 sqrtPriceX96, uint128 liquidity, int24 tick)
SWAP_TOPIC_V3 = Web3.keccak(
    text="Swap(address,address,int256,int256,uint160,uint128,int24)"
).hex()

# Transfer event (ERC20)
TRANSFER_TOPIC = Web3.keccak(text="Transfer(address,address,uint256)").hex()

# Known DEX factory addresses on Mantle (for pair identification)
KNOWN_FACTORIES = {
    "0x4515A45337F461A11Ff0FE8aBF3c606AE5dC00c9": "merchant_moe",
}

# Known DEX pair patterns (cached as we discover them)
_DISCOVERED_PAIRS: dict[str, str] = {}


@dataclass
class SwapEvent:
    """Represents a DEX swap detected on-chain."""

    dex: str  # "merchant_moe", "agni_finance", "fluxion", "unknown"
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

    Listens for Swap events from ANY contract on the network,
    automatically identifying DEXes by factory address patterns.
    """

    def __init__(self, client: MantleClient | None = None) -> None:
        self.client = client or MantleClient()
        self._seen_txs: set[str] = set()

    def get_swaps_in_block(self, block_number: int) -> list[SwapEvent]:
        """
        Query all Swap events emitted in a given block from any DEX.
        Returns a list of normalized SwapEvent objects.
        """
        events: list[SwapEvent] = []

        # Get all logs with Swap topic in this block
        for topic in [SWAP_TOPIC_V2, SWAP_TOPIC_V3]:
            try:
                filter_params = {
                    "fromBlock": block_number,
                    "toBlock": block_number,
                    "topics": [topic],
                }
                logs = self.client.get_logs(filter_params)

                for log in logs:
                    try:
                        event = self._parse_swap_log(log, topic)
                        if event and event.tx_hash not in self._seen_txs:
                            events.append(event)
                            self._seen_txs.add(event.tx_hash)
                    except Exception as e:
                        logger.debug("Failed to parse swap log: %s", e)
                        continue
            except Exception as e:
                logger.debug("Failed to get logs for block %d: %s", block_number, e)
                continue

        # Trim seen txs cache to prevent memory leak
        if len(self._seen_txs) > 10000:
            self._seen_txs = set(list(self._seen_txs)[-5000:])

        return events

    def _parse_swap_log(self, log: dict, topic: str) -> SwapEvent | None:
        """Parse a raw log into a SwapEvent."""
        try:
            log_data = dict(log)
            tx_hash = log_data["transactionHash"].hex() if hasattr(log_data["transactionHash"], "hex") else str(log_data["transactionHash"])
            block_number = log_data["blockNumber"]
            log_index = log_data.get("logIndex", 0)
            pair_address = log_data.get("address", "0x").lower() if isinstance(log_data.get("address"), str) else "0x"
            topics = log_data.get("topics", [])

            # Identify DEX by checking if pair was created by known factory
            dex_name = _DISCOVERED_PAIRS.get(pair_address, "unknown")

            if topic == SWAP_TOPIC_V2:
                return self._parse_v2_swap(log_data, tx_hash, block_number, log_index, pair_address, dex_name)
            elif topic == SWAP_TOPIC_V3:
                return self._parse_v3_swap(log_data, tx_hash, block_number, log_index, pair_address, dex_name)
        except Exception as e:
            logger.debug("Error parsing swap: %s", e)
        return None

    def _parse_v2_swap(self, log_data, tx_hash, block_number, log_index, pair_address, dex_name) -> SwapEvent | None:
        """Parse a V2-style Swap event."""
        data = log_data.get("data", b"")
        topics = log_data.get("topics", [])

        if isinstance(data, str) and data.startswith("0x"):
            data = bytes.fromhex(data[2:])

        if len(data) < 128:
            return None

        amount0_in = int.from_bytes(data[0:32], "big")
        amount1_in = int.from_bytes(data[32:64], "big")
        amount0_out = int.from_bytes(data[64:96], "big")
        amount1_out = int.from_bytes(data[96:128], "big")

        sender = "0x" + topics[1].hex()[-40:] if len(topics) > 1 else "0x"
        to = "0x" + topics[2].hex()[-40:] if len(topics) > 2 else "0x"

        amount_in = max(amount0_in, amount1_in)
        amount_out = max(amount0_out, amount1_out)

        if amount_in == 0 and amount_out == 0:
            return None

        return SwapEvent(
            dex=dex_name,
            tx_hash=tx_hash,
            block_number=block_number,
            log_index=log_index,
            sender=Web3.to_checksum_address(sender),
            to=Web3.to_checksum_address(to),
            amount_in=amount_in,
            amount_out=amount_out,
            pair_address=pair_address,
            raw_log={"type": "v2", "amount0_in": amount0_in, "amount1_in": amount1_in,
                     "amount0_out": amount0_out, "amount1_out": amount1_out},
        )

    def _parse_v3_swap(self, log_data, tx_hash, block_number, log_index, pair_address, dex_name) -> SwapEvent | None:
        """Parse a V3-style Swap event."""
        data = log_data.get("data", b"")
        topics = log_data.get("topics", [])

        if isinstance(data, str) and data.startswith("0x"):
            data = bytes.fromhex(data[2:])

        if len(data) < 160:
            return None

        amount0 = int.from_bytes(data[0:32], "big", signed=True)
        amount1 = int.from_bytes(data[32:64], "big", signed=True)

        sender = "0x" + topics[1].hex()[-40:] if len(topics) > 1 else "0x"
        to = "0x" + topics[2].hex()[-40:] if len(topics) > 2 else "0x"

        # In V3, negative amounts mean tokens going out
        amount_in = max(amount0, amount1) if max(amount0, amount1) > 0 else 0
        amount_out = abs(min(amount0, amount1)) if min(amount0, amount1) < 0 else 0

        if amount_in == 0 and amount_out == 0:
            return None

        return SwapEvent(
            dex=dex_name,
            tx_hash=tx_hash,
            block_number=block_number,
            log_index=log_index,
            sender=Web3.to_checksum_address(sender),
            to=Web3.to_checksum_address(to),
            amount_in=abs(amount_in),
            amount_out=amount_out,
            pair_address=pair_address,
            raw_log={"type": "v3", "amount0": amount0, "amount1": amount1},
        )

    def discover_pair_dex(self, pair_address: str, factory_address: str | None = None) -> str:
        """
        Try to identify which DEX a pair belongs to.
        Caches the result for future lookups.
        """
        pair_lower = pair_address.lower()
        if pair_lower in _DISCOVERED_PAIRS:
            return _DISCOVERED_PAIRS[pair_lower]

        if factory_address:
            factory_lower = factory_address.lower()
            dex_name = KNOWN_FACTORIES.get(factory_lower, "unknown")
            _DISCOVERED_PAIRS[pair_lower] = dex_name
            return dex_name

        return "unknown"
