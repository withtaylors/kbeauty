"""
Home-country price from the open web — the way a person (or a chat assistant) would look it up.

1. Ask a web search API for the product in the home market ("<brand> <name> price").
2. Read the result snippets and pull prices out with plain regular expressions — no LLM, so no
   invented numbers: every price we use appears verbatim in a source we can link to.
3. Keep only sources that look like this product, outside Korea, priced within a sane band of the
   Korean price; require at least two independent domains; report the median and the sources.

If that bar isn't met we return nothing and the engine keeps saying "ruling deferred".
Search provider: Tavily (free tier, keyed).  Results are cached for a day, misses included,
so the free monthly credits go a long way.
"""
from __future__ import annotations

import logging
import re
import statistics
import time
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

import httpx

log = logging.getLogger(__name__)

PRICE_PATTERNS: dict[str, tuple[re.Pattern, ...]] = {
    "USD": (re.compile(r"(?:US\s?)?\$\s?(\d{1,4}(?:,\d{3})*(?:\.\d{1,2})?)"),
            re.compile(r"USD\s?(\d{1,4}(?:,\d{3})*(?:\.\d{1,2})?)")),
    "JPY": (re.compile(r"[¥￥]\s?(\d{1,3}(?:,\d{3})+|\d{2,6})"),
            re.compile(r"(\d{1,3}(?:,\d{3})+|\d{3,6})\s?円")),
}
COUNTRY = {"USD": "united states", "JPY": "japan"}
QUERY = {"USD": "{q} price", "JPY": "{q} 価格"}
KOREAN_TLDS = (".kr",)
MIN_SOURCES = 2
BAND = (0.5, 4.0)          # home price must sit between 0.5× and 4× the Korean price (same currency)


@dataclass(frozen=True)
class Source:
    url: str
    domain: str
    price: float


@dataclass(frozen=True)
class WebPrice:
    currency: str
    price: float                     # median of the accepted sources
    sources: tuple[Source, ...]
    query: str

    def to_dict(self) -> dict:
        return {"kind": "web", "currency": self.currency, "price": self.price, "query": self.query,
                "sources": [{"url": s.url, "domain": s.domain, "price": s.price} for s in self.sources]}


class WebSearchClient(Protocol):
    async def search(self, query: str, country: str | None, max_results: int) -> list[dict]: ...


class TavilyClient:
    URL = "https://api.tavily.com/search"

    def __init__(self, api_key: str, timeout: float = 12.0):
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._timeout = timeout

    async def search(self, query: str, country: str | None, max_results: int = 8) -> list[dict]:
        body = {"query": query, "search_depth": "basic", "max_results": max_results, "topic": "general"}
        if country:
            body["country"] = country
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.post(self.URL, headers=self._headers, json=body)
            r.raise_for_status()
            return r.json().get("results", [])


def _tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 2}


def _first_price(text: str, currency: str) -> float | None:
    hits = []
    for pat in PRICE_PATTERNS[currency]:
        for m in pat.finditer(text):
            try:
                hits.append((m.start(), float(m.group(1).replace(",", ""))))
            except ValueError:
                continue
    return min(hits)[1] if hits else None          # the first price in the snippet


def extract(results: list[dict], currency: str, brand: str, name: str, korea_local: float) -> list[Source]:
    """Pure function: search results → accepted price sources (one per domain)."""
    want = _tokens(f"{brand} {name}")
    brand_tokens = _tokens(brand)
    lo, hi = BAND[0] * korea_local, BAND[1] * korea_local
    out: dict[str, Source] = {}
    for r in results:
        url = r.get("url") or ""
        domain = urlparse(url).netloc.lower().removeprefix("www.")
        if not domain or domain.endswith(KOREAN_TLDS) or domain in out:
            continue
        text = f"{r.get('title', '')} {r.get('content', '')}"
        have = _tokens(text)
        if brand_tokens and not brand_tokens & have:
            continue                                     # not this brand
        if len(want & have) < min(3, len(want)):
            continue                                     # not this product
        price = _first_price(r.get("content", "") or r.get("title", ""), currency)
        if price is None or not lo <= price <= hi:
            continue
        out[domain] = Source(url, domain, price)
    return list(out.values())


class WebPriceFinder:
    def __init__(self, client: WebSearchClient | None, ttl_s: int = 24 * 3600):
        self._client = client
        self._ttl = ttl_s
        self._cache: dict[tuple[str, str], tuple[float, WebPrice | None]] = {}
        self.calls = 0

    @property
    def enabled(self) -> bool:
        return self._client is not None

    async def lookup(self, brand: str, name: str, currency: str, korea_local: float) -> WebPrice | None:
        if self._client is None or currency not in PRICE_PATTERNS:
            return None
        q = " ".join(f"{brand} {name}".split())
        key = (q.lower(), currency)
        hit = self._cache.get(key)
        if hit and time.time() - hit[0] < self._ttl:
            return hit[1]
        query = QUERY[currency].format(q=q)
        try:
            self.calls += 1
            results = await self._client.search(query, COUNTRY.get(currency), 8)
        except httpx.HTTPError as e:
            log.warning("web price search failed: %s", e)
            return None                                   # not cached: try again next time
        sources = extract(results, currency, brand, name, korea_local)
        found = None
        if len(sources) >= MIN_SOURCES:
            found = WebPrice(currency, round(statistics.median(s.price for s in sources), 2 if currency == "USD" else 0),
                             tuple(sources), query)
        self._cache[key] = (time.time(), found)
        return found
