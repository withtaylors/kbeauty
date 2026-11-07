"""
Live product source — real products currently sold in Korea.

Olive Young's own site sits behind a bot wall, so we use the Naver Shopping Search API
(free, keyed) and keep only listings sold by Olive Young when the caller asks for it.
Results are normalized into the same `Product` type the engine uses; category and
ingredient tags are derived from the Korean product title with a keyword table, so
skin-fit and duplicate rules work on live items too.  Home-country prices are unknown
for live items — the engine reports that honestly instead of guessing.
"""
from __future__ import annotations

import html
import logging
import re
import time
from dataclasses import dataclass
from typing import Protocol

import httpx

from .catalog import Product

log = logging.getLogger(__name__)

# ---------- keyword tagging (Korean + English titles) ----------

CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("sunscreen", ("선크림", "선세럼", "선스틱", "선쿠션", "선젤", "선로션", "sunscreen", "sun cream", "sun serum", "spf")),
    ("cleanser",  ("클렌징", "클렌저", "폼클렌징", "클렌징폼", "클렌징오일", "클렌징밤", "cleanser", "cleansing")),
    ("pad",       ("패드", "토너패드", "pad")),
    ("mask",      ("마스크", "마스크팩", "시트마스크", "슬리핑팩", "슬리핑 마스크", "mask", "pack")),
    ("toner",     ("토너", "스킨", "화장수", "toner")),
    ("serum",     ("세럼", "에센스", "앰플", "serum", "essence", "ampoule")),
    ("cream",     ("크림", "로션", "에멀전", "밤", "cream", "lotion", "moisturizer")),
    ("cushion",   ("쿠션", "파운데이션", "cushion", "foundation")),
    ("blush",     ("블러셔", "블러쉬", "치크", "blush")),
    ("lip",       ("립", "틴트", "립밤", "립스틱", "글로스", "lip", "tint")),
    ("base",      ("프라이머", "톤업", "베이스", "컬러 코렉팅", "primer", "tone up")),
]

TAG_KEYWORDS: dict[str, tuple[str, ...]] = {
    "heartleaf": ("어성초", "heartleaf", "houttuynia"),
    "centella": ("센텔라", "병풀", "시카", "centella", "cica"),
    "hyaluronic_acid": ("히알루론", "hyaluron"),
    "panthenol": ("판테놀", "panthenol", "b5"),
    "niacinamide": ("나이아신", "niacinamide"),
    "vitamin_c": ("비타민c", "비타민 c", "vita c", "vitamin c", "아스코르빅"),
    "retinol": ("레티놀", "retinol", "레티날"),
    "ceramide": ("세라마이드", "ceramide"),
    "collagen": ("콜라겐", "collagen"),
    "peptide": ("펩타이드", "peptide", "pdrn"),
    "propolis": ("프로폴리스", "propolis"),
    "snail_mucin": ("달팽이", "스네일", "snail", "뮤신", "mucin"),
    "rice": ("쌀", "라이스", "rice"),
    "green_tea": ("녹차", "그린티", "green tea"),
    "tea_tree": ("티트리", "tea tree"),
    "bha": ("bha", "살리실", "salicylic"),
    "aha": ("aha", "글리콜", "glycolic", "락틱"),
    "exfoliating": ("필링", "각질", "peeling", "exfoliat"),
    "pore_care": ("모공", "pore"),
    "oil_control": ("피지", "sebum", "oil control", "매트"),
    "soothing": ("진정", "수딩", "soothing", "calming", "릴리프", "relief"),
    "hydrating": ("수분", "보습", "촉촉", "hydrat", "moist", "워터"),
    "barrier": ("장벽", "barrier", "아토"),
    "brightening": ("미백", "브라이트닝", "brighten", "광채", "글로우", "glow", "톤업"),
    "spf50": ("spf50", "spf 50", "pa++++"),
    "fragrance_free": ("무향", "fragrance free", "fragrance-free"),
    "glossy": ("글로시", "글래스", "glossy", "glass", "glasting", "물광"),
    "matte": ("매트", "벨벳", "matte", "velvet"),
    "long_lasting": ("롱래스팅", "래스팅", "lasting", "픽서", "fixer"),
    "tint": ("틴트", "tint"),
    "overnight": ("슬리핑", "나이트", "sleeping", "overnight"),
    "low_ph": ("약산성", "low ph", "ph 5.5"),
}

_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(s: str) -> str:
    return html.unescape(_TAG_RE.sub("", s or "")).strip()


def tag_title(title: str) -> tuple[str, tuple[str, ...]]:
    """(category, tags) from a product title.  Deterministic, table-driven."""
    t = title.lower()
    category = "unknown"
    for cat, words in CATEGORY_KEYWORDS:
        if any(w in t for w in words):
            category = cat
            break
    tags = tuple(tag for tag, words in TAG_KEYWORDS.items() if any(w in t for w in words))
    return category, tags


# ---------- live product ----------

@dataclass(frozen=True)
class LiveProduct:
    id: str                 # "live:<naver productId>", or "web:<hash>" for a product typed in by the user
    title: str
    brand: str
    maker: str
    price_krw: int
    image: str
    link: str
    mall: str
    category_path: str

    @property
    def brand_name(self) -> str:
        return self.brand or self.maker or ""

    @property
    def name(self) -> str:
        """Title without a leading brand, so "brand + name" renders once."""
        b = self.brand_name
        t = self.title
        if b and t.lower().startswith(b.lower()):
            t = t[len(b):].strip(" -·")
        return t or self.title

    def to_product(self) -> Product:
        category, tags = tag_title(f"{self.brand} {self.title} {self.category_path}")
        # rebuy_url stays empty: the store link is a Korean listing, not a way to re-buy at home.
        return Product(
            id=self.id, brand_en=self.brand_name, brand_ko=self.brand_name,
            name_en=self.name, name_ko=self.name, category=category, tags=tags, size="",
            price_krw=self.price_krw, home_price={}, rebuy_url="", image=self.image,
        )

    def brief(self) -> dict:
        return {"id": self.id, "brand": self.brand_name, "name": self.name, "name_ko": self.name,
                "price_krw": self.price_krw, "image": self.image, "category": tag_title(self.title)[0],
                "mall": self.mall, "link": self.link, "source": "manual" if self.id.startswith("web:") else "live"}


class ShoppingClient(Protocol):
    async def search(self, query: str, display: int) -> list[dict]: ...


class NaverShoppingClient:
    """Naver Shopping Search API (https://developers.naver.com)."""

    URL = "https://openapi.naver.com/v1/search/shop.json"

    def __init__(self, client_id: str, client_secret: str, timeout: float = 10.0):
        self._headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
        self._timeout = timeout

    async def search(self, query: str, display: int = 30) -> list[dict]:
        async with httpx.AsyncClient(timeout=self._timeout) as c:
            r = await c.get(self.URL, headers=self._headers, params={"query": query, "display": display, "sort": "sim"})
            r.raise_for_status()
            return r.json().get("items", [])


OLIVE_YOUNG_MALLS = ("올리브영", "oliveyoung", "olive young")


class LiveSearch:
    """Search real listings; optionally only those sold by Olive Young.  Caches results so a
    selected item can be re-fetched by id for the detail page and the shopping list."""

    def __init__(self, client: ShoppingClient | None, cache_ttl_s: int = 3600):
        self._client = client
        self._cache: dict[str, tuple[float, LiveProduct]] = {}
        self._ttl = cache_ttl_s

    @property
    def enabled(self) -> bool:
        return self._client is not None

    async def search(self, query: str, olive_young_only: bool = True, limit: int = 10) -> list[LiveProduct]:
        if self._client is None or not query.strip():
            return []
        try:
            items = await self._client.search(query, display=40 if olive_young_only else limit)
        except httpx.HTTPError as e:
            log.warning("live search failed: %s", e)
            return []
        out: list[LiveProduct] = []
        seen: set[str] = set()
        for it in items:
            mall = strip_html(it.get("mallName", ""))
            if olive_young_only and not any(m in mall.lower() for m in OLIVE_YOUNG_MALLS):
                continue
            pid = str(it.get("productId") or "")
            if not pid or pid in seen:
                continue
            try:
                price = int(it.get("lprice") or 0)
            except ValueError:
                price = 0
            if price <= 0:
                continue
            seen.add(pid)
            p = LiveProduct(
                id=f"live:{pid}", title=strip_html(it.get("title", "")), brand=strip_html(it.get("brand", "")),
                maker=strip_html(it.get("maker", "")), price_krw=price, image=it.get("image", ""),
                link=it.get("link", ""), mall=mall,
                category_path=" ".join(strip_html(it.get(f"category{i}", "")) for i in range(1, 5)),
            )
            self._cache[p.id] = (time.time(), p)
            out.append(p)
            if len(out) >= limit:
                break
        return out

    def get(self, live_id: str) -> LiveProduct | None:
        hit = self._cache.get(live_id)
        if not hit:
            return None
        ts, p = hit
        if time.time() - ts > self._ttl:
            del self._cache[live_id]
            return None
        return p

    def remember(self, p: LiveProduct) -> None:
        self._cache[p.id] = (time.time(), p)
