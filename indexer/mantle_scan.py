"""
Mantlescan API client for Mantle Alpha.

Provides async access to the Mantlescan block explorer API for:
- Top account discovery (whale detection)
- Account balance queries
- Transaction history
- ERC-20 token transfers
- Internal transactions

All responses are cached with configurable TTL to respect rate limits.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TopAccount:
    """A top MNT holder on Mantle."""
    address: str
    balance_mnt: float
    rank: int


@dataclass(frozen=True)
class Transaction:
    """A normal transaction entry."""
    hash: str
    block_number: int
    timestamp: int
    from_address: str
    to_address: str
    value_mnt: float
    gas_used: int
    gas_price: int
    is_error: bool


@dataclass(frozen=True)
class TokenTransfer:
    """An ERC-20 token transfer event."""
    hash: str
    block_number: int
    timestamp: int
    from_address: str
    to_address: str
    value: str
    token_name: str
    token_symbol: str
    contract_address: str


@dataclass(frozen=True)
class InternalTransaction:
    """An internal transaction."""
    hash: str
    block_number: int
    timestamp: int
    from_address: str
    to_address: str
    value_mnt: float
    type: str


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

@dataclass
class _CacheEntry:
    data: Any
    expires_at: float


class _TTLCache:
    """Simple in-memory TTL cache."""

    def __init__(self, default_ttl: float = 300.0) -> None:
        self._store: dict[str, _CacheEntry] = {}
        self._default_ttl = default_ttl

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        if time.monotonic() > entry.expires_at:
            del self._store[key]
            return None
        return entry.data

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        self._store[key] = _CacheEntry(
            data=value,
            expires_at=time.monotonic() + (ttl or self._default_ttl),
        )

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

class _RateLimiter:
    """Token-bucket rate limiter (async-safe)."""

    def __init__(self, rate: float = 5.0) -> None:
        self._rate = rate
        self._interval = 1.0 / rate
        self._lock = asyncio.Lock()
        self._last: float = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._last + self._interval - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()


# ---------------------------------------------------------------------------
# Mantlescan client
# ---------------------------------------------------------------------------

class MantlescanClient:
    """
    Async client for the Mantlescan API.

    Features:
    - Automatic rate limiting (5 req/s default)
    - Response caching with TTL
    - Whale wallet auto-discovery
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        cache_ttl: float = 300.0,
        rate_limit: float = 5.0,
    ) -> None:
        self._api_key = api_key or settings.mantlescan_api_key
        self._base_url = (base_url or settings.mantlescan_api_url).rstrip("/")
        self._limiter = _RateLimiter(rate=rate_limit)
        self._cache = _TTLCache(default_ttl=cache_ttl)
        self._client: httpx.AsyncClient | None = None

    # -- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        """Create the underlying HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=httpx.Timeout(30.0),
                headers={"Accept": "application/json"},
            )
            logger.info("MantlescanClient started (base=%s)", self._base_url)

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.info("MantlescanClient closed")

    async def __aenter__(self) -> "MantlescanClient":
        await self.start()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    # -- internal helpers ---------------------------------------------------

    async def _get(self, params: dict[str, Any], cache_key: str | None = None, cache_ttl: float | None = None) -> dict:
        """Execute a rate-limited, optionally cached GET request."""
        if cache_key:
            cached = self._cache.get(cache_key)
            if cached is not None:
                logger.debug("Cache hit: %s", cache_key)
                return cached

        if self._client is None:
            raise RuntimeError("Client not started — call `await start()` first")

        params["apikey"] = self._api_key
        await self._limiter.acquire()

        try:
            resp = await self._client.get("", params=params)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as exc:
            logger.error("HTTP %s for %s: %s", exc.response.status_code, params, exc.response.text[:500])
            raise
        except httpx.RequestError as exc:
            logger.error("Request failed for %s: %s", params, exc)
            raise

        if cache_key:
            self._cache.set(cache_key, data, ttl=cache_ttl)

        return data

    @staticmethod
    def _ensure_list(data: Any) -> list:
        if isinstance(data, list):
            return data
        return []

    # -- public API ---------------------------------------------------------

    async def get_top_accounts(self, count: int = 20) -> list[TopAccount]:
        """
        Fetch the top MNT holders on Mantle.

        Returns a list of TopAccount sorted by balance descending.
        """
        cache_key = f"top_accounts:{count}"
        raw = await self._get(
            params={"module": "account", "action": "topaccounts", "page": 1, "offset": count, "sort": "desc"},
            cache_key=cache_key,
            cache_ttl=600.0,
        )

        accounts: list[TopAccount] = []
        for i, entry in enumerate(self._ensure_list(raw.get("result")), start=1):
            try:
                accounts.append(
                    TopAccount(
                        address=entry.get("address", ""),
                        balance_mnt=float(entry.get("balance", 0)) / 1e18,
                        rank=i,
                    )
                )
            except (TypeError, ValueError) as exc:
                logger.warning("Skipping top account entry %d: %s", i, exc)

        logger.info("Fetched %d top accounts", len(accounts))
        return accounts

    async def get_account_balance(self, address: str) -> float:
        """
        Get the MNT balance for a single address.

        Returns balance in MNT (not wei).
        """
        cache_key = f"balance:{address}"
        raw = await self._get(
            params={"module": "account", "action": "balance", "address": address, "tag": "latest"},
            cache_key=cache_key,
        )

        result = raw.get("result", "0")
        try:
            balance_wei = int(result)
        except (TypeError, ValueError):
            logger.warning("Unexpected balance response for %s: %s", address, result)
            return 0.0

        return balance_wei / 1e18

    async def get_transactions(
        self,
        address: str,
        page: int = 1,
        offset: int = 20,
    ) -> list[Transaction]:
        """
        Get recent normal transactions for an address.

        Args:
            address: Wallet address.
            page: Page number (1-indexed).
            offset: Results per page (max 100).
        """
        cache_key = f"txs:{address}:{page}:{offset}"
        raw = await self._get(
            params={
                "module": "account",
                "action": "txlist",
                "address": address,
                "startblock": 0,
                "endblock": 99999999,
                "page": page,
                "offset": offset,
                "sort": "desc",
            },
            cache_key=cache_key,
            cache_ttl=60.0,
        )

        txs: list[Transaction] = []
        for entry in self._ensure_list(raw.get("result")):
            try:
                txs.append(
                    Transaction(
                        hash=entry.get("hash", ""),
                        block_number=int(entry.get("blockNumber", 0)),
                        timestamp=int(entry.get("timeStamp", 0)),
                        from_address=entry.get("from", ""),
                        to_address=entry.get("to", ""),
                        value_mnt=float(entry.get("value", 0)) / 1e18,
                        gas_used=int(entry.get("gasUsed", 0)),
                        gas_price=int(entry.get("gasPrice", 0)),
                        is_error=entry.get("isError", "0") == "1",
                    )
                )
            except (TypeError, ValueError) as exc:
                logger.warning("Skipping tx entry: %s", exc)

        logger.debug("Fetched %d transactions for %s", len(txs), address)
        return txs

    async def get_token_transfers(self, address: str) -> list[TokenTransfer]:
        """
        Get ERC-20 token transfers for an address.
        """
        cache_key = f"token_transfers:{address}"
        raw = await self._get(
            params={
                "module": "account",
                "action": "tokentx",
                "address": address,
                "startblock": 0,
                "endblock": 99999999,
                "sort": "desc",
            },
            cache_key=cache_key,
            cache_ttl=60.0,
        )

        transfers: list[TokenTransfer] = []
        for entry in self._ensure_list(raw.get("result")):
            try:
                transfers.append(
                    TokenTransfer(
                        hash=entry.get("hash", ""),
                        block_number=int(entry.get("blockNumber", 0)),
                        timestamp=int(entry.get("timeStamp", 0)),
                        from_address=entry.get("from", ""),
                        to_address=entry.get("to", ""),
                        value=entry.get("value", "0"),
                        token_name=entry.get("tokenName", ""),
                        token_symbol=entry.get("tokenSymbol", ""),
                        contract_address=entry.get("contractAddress", ""),
                    )
                )
            except (TypeError, ValueError) as exc:
                logger.warning("Skipping token transfer entry: %s", exc)

        logger.debug("Fetched %d token transfers for %s", len(transfers), address)
        return transfers

    async def get_internal_transactions(self, address: str) -> list[InternalTransaction]:
        """
        Get internal transactions for an address.
        """
        cache_key = f"internal_txs:{address}"
        raw = await self._get(
            params={
                "module": "account",
                "action": "txlistinternal",
                "address": address,
                "startblock": 0,
                "endblock": 99999999,
                "sort": "desc",
            },
            cache_key=cache_key,
            cache_ttl=60.0,
        )

        txs: list[InternalTransaction] = []
        for entry in self._ensure_list(raw.get("result")):
            try:
                txs.append(
                    InternalTransaction(
                        hash=entry.get("hash", ""),
                        block_number=int(entry.get("blockNumber", 0)),
                        timestamp=int(entry.get("timeStamp", 0)),
                        from_address=entry.get("from", ""),
                        to_address=entry.get("to", ""),
                        value_mnt=float(entry.get("value", 0)) / 1e18,
                        type=entry.get("type", ""),
                    )
                )
            except (TypeError, ValueError) as exc:
                logger.warning("Skipping internal tx entry: %s", exc)

        logger.debug("Fetched %d internal txs for %s", len(txs), address)
        return txs

    # -- whale discovery ----------------------------------------------------

    async def discover_whale_wallets(self, count: int | None = None) -> list[str]:
        """
        Auto-discover the top whale wallets by MNT balance.

        Merges discovered wallets with any statically configured ones in
        settings.whale_wallets.  Returns a deduplicated list of addresses.

        Args:
            count: Number of top accounts to fetch.  Defaults to
                   settings.whale_discover_count.
        """
        n = count or settings.whale_discover_count
        accounts = await self.get_top_accounts(count=n)

        discovered = [a.address for a in accounts if a.address]
        static = [w for w in settings.whale_wallets if w]

        # Preserve order: static first, then discovered, deduplicated
        seen: set[str] = set()
        merged: list[str] = []
        for addr in static + discovered:
            addr_lower = addr.lower()
            if addr_lower not in seen:
                seen.add(addr_lower)
                merged.append(addr)

        logger.info(
            "Whale discovery: %d static + %d discovered = %d unique wallets",
            len(static),
            len(discovered),
            len(merged),
        )
        return merged
