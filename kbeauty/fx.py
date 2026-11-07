"""
Exchange rates — live when reachable, otherwise the reference table in rules.json.

Source: Frankfurter (https://frankfurter.dev), a free, keyless API over ECB reference rates.
The engine never calls the network; it gets a `Rules` whose fx table was swapped here.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, replace
from typing import Protocol

import httpx

from .catalog import Currency, Rules

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FxSnapshot:
    as_of: str                              # ISO date from the source
    krw_per_unit: dict[Currency, float]     # KRW for 1 unit of each home currency
    source: str                             # "frankfurter" | "rules.json"


class FxClient(Protocol):
    async def latest(self, currencies: tuple[Currency, ...]) -> FxSnapshot: ...


class FrankfurterClient:
    URL = "https://api.frankfurter.dev/v1/latest"

    def __init__(self, timeout: float = 6.0):
        self._timeout = timeout

    async def latest(self, currencies: tuple[Currency, ...]) -> FxSnapshot:
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.get(self.URL, params={"from": "KRW", "to": ",".join(currencies)})
            r.raise_for_status()
            d = r.json()
        # Frankfurter gives units of each currency per 1 KRW; the engine wants KRW per unit.
        return FxSnapshot(d["date"], {cur: round(1 / float(rate), 4) for cur, rate in d["rates"].items()}, "frankfurter")


class LiveFx:
    """Keeps the latest snapshot; `apply()` returns rules with that fx table (or the file's if none)."""

    def __init__(self, client: FxClient | None, currencies: tuple[Currency, ...], ttl_s: int = 6 * 3600):
        self._client, self._currencies, self._ttl = client, currencies, ttl_s
        self._snap: FxSnapshot | None = None
        self._fetched_at = 0.0

    @property
    def snapshot(self) -> FxSnapshot | None:
        return self._snap

    @property
    def stale(self) -> bool:
        return self._client is not None and time.time() - self._fetched_at > self._ttl

    async def refresh(self) -> FxSnapshot | None:
        if self._client is None:
            return None
        try:
            self._snap = await self._client.latest(self._currencies)
            self._fetched_at = time.time()
            log.info("fx %s as of %s: %s", self._snap.source, self._snap.as_of, self._snap.krw_per_unit)
        except (httpx.HTTPError, KeyError, ValueError, ZeroDivisionError) as e:
            log.warning("fx refresh failed, keeping %s: %s", "previous" if self._snap else "rules.json", e)
        return self._snap

    def apply(self, rules: Rules) -> Rules:
        if self._snap is None:
            return rules
        merged = {**rules.fx_krw_per_unit, **self._snap.krw_per_unit}
        return replace(rules, fx_krw_per_unit=merged, as_of=self._snap.as_of)
