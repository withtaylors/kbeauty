"""
상품 공유 링크 → 상품명·가격·대표 이미지 수집 (증거 수집)

1차: OpenGraph / JSON-LD 메타태그 (카톡 미리보기가 쓰는 것과 같은 정보)
2차: 플랫폼별 셀렉터
실패하면 {"ok": False, "reason": ...} 를 돌려주고, 화면은 '증거 보강' 버튼을 띄웁니다.
"""
from __future__ import annotations

import json
import re
from typing import Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")

GENERIC_TITLES = ["지그재그 스토어", "모든 취향 곁에", "무신사 스토어", "쿠팡!", "ZIGZAG", "로그인", "앱에서 보기"]

PLATFORM_HOSTS = {
    "musinsa": ["musinsa.com"],
    "29cm": ["29cm.co.kr"],
    "zigzag": ["zigzag.kr", "kakaostyle.com"],
    "coupang": ["coupang.com", "coupa.ng"],
    "ably": ["a-bly.com"],
}


def detect_platform(url: str) -> str:
    host = urlparse(url).netloc.lower()
    for p, hosts in PLATFORM_HOSTS.items():
        if any(h in host for h in hosts):
            return p
    return host.replace("www.", "") or "unknown"


def parse_price(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    m = re.findall(r"\d[\d,]{2,}", text)
    nums = [int(x.replace(",", "")) for x in m]
    nums = [n for n in nums if 1000 <= n <= 50_000_000]
    return min(nums) if nums else None          # 할인가가 보통 더 작음


def _meta(soup: BeautifulSoup, *names: str) -> Optional[str]:
    for n in names:
        tag = soup.find("meta", property=n) or soup.find("meta", attrs={"name": n})
        if tag and tag.get("content"):
            return tag["content"].strip()
    return None


def _jsonld_product(soup: BeautifulSoup) -> dict:
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(s.string or "")
        except Exception:
            continue
        for d in (data if isinstance(data, list) else [data]):
            if isinstance(d, dict) and d.get("@type") in ("Product", ["Product"]):
                offers = d.get("offers") or {}
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                img = d.get("image")
                if isinstance(img, list):
                    img = img[0] if img else None
                return {"name": d.get("name"), "price": offers.get("price"), "image": img}
    return {}


def extract_from_html(html: str, url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    ld = _jsonld_product(soup)
    name = ld.get("name") or _meta(soup, "og:title", "twitter:title") or (soup.title.string if soup.title else None)
    price_raw = ld.get("price") or _meta(soup, "product:price:amount", "og:price:amount", "twitter:data1")
    price = parse_price(str(price_raw)) if price_raw else None
    if price is None:
        # 설명/본문에서 '원' 붙은 숫자
        desc = _meta(soup, "og:description", "description") or ""
        price = parse_price(desc)
    if price is None:
        text = soup.get_text(" ", strip=True)[:20000]
        m = re.search(r"(\d[\d,]{3,})\s*원", text)
        price = parse_price(m.group(0)) if m else None
    image = ld.get("image") or _meta(soup, "og:image", "twitter:image")
    if name:
        name = re.sub(r"\s*[-|·]\s*(무신사|29CM|지그재그|쿠팡|ZIGZAG|MUSINSA).*$", "", name).strip()
    return {"name": name, "price": price, "image": image, "platform": detect_platform(url), "url": url}


async def fetch_product(url: str, timeout: float = 12.0) -> dict:
    """공유 링크에서 상품 정보 수집. 실패 시 ok=False."""
    platform = detect_platform(url)
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout,
                                     headers={"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"}) as c:
            r = await c.get(url)
        if r.status_code >= 400:
            return {"ok": False, "platform": platform, "url": str(r.url),
                    "reason": f"HTTP {r.status_code} (쇼핑몰이 자동 수집을 막음)"}
        data = extract_from_html(r.text, str(r.url))
        if data.get("name") and any(g in data["name"] for g in GENERIC_TITLES):
            data["name"] = None          # 상품 페이지가 아니라 홈/앱 유도 페이지가 내려옴
            data["price"] = None
        missing = [k for k in ("name", "price", "image") if not data.get(k)]
        data["ok"] = len(missing) == 0
        data["missing"] = missing
        if missing:
            data["reason"] = f"{', '.join(missing)} 를 찾지 못함 (증거 보강 필요)"
        return data
    except Exception as e:  # 네트워크, 타임아웃 등
        return {"ok": False, "platform": platform, "url": url, "reason": f"접속 실패: {type(e).__name__}"}
