"""Live (Naver Shopping) source — exercised through a fake client; no network."""
import pytest

from kbeauty.catalog import Catalog
from kbeauty.engine import Line, Profile, scan, summarize
from kbeauty.sources import LiveSearch, strip_html, tag_title

NAVER_ITEMS = [  # shape of the real API response
    {"title": "<b>아누아</b> 어성초 77 수딩 토너 250ml", "link": "https://smartstore.naver.com/x/1", "image": "https://img/1.jpg",
     "lprice": "21900", "mallName": "올리브영", "productId": "111", "brand": "아누아", "maker": "아누아", "category3": "스킨/토너"},
    {"title": "아누아 어성초 77 수딩 토너 250ml 대용량", "link": "https://other/2", "image": "", "lprice": "19900",
     "mallName": "쿠팡", "productId": "222", "brand": "아누아", "maker": "", "category3": "스킨/토너"},
    {"title": "[올리브영] 라운드랩 자작나무 수분 선크림 SPF50+ PA++++", "link": "https://oy/3", "image": "https://img/3.jpg",
     "lprice": "18900", "mallName": "CJ올리브영", "productId": "333", "brand": "라운드랩", "maker": "", "category3": "선케어"},
    {"title": "가격없는 상품", "lprice": "0", "mallName": "올리브영", "productId": "444"},
]


class FakeNaver:
    def __init__(self, items):
        self.items, self.calls = items, []

    async def search(self, query, display):
        self.calls.append((query, display))
        return self.items


def test_tag_title_korean_and_english():
    assert tag_title("아누아 어성초 77 수딩 토너 250ml") == ("toner", ("heartleaf", "soothing"))
    cat, tags = tag_title("라운드랩 자작나무 수분 선크림 SPF50+ PA++++")
    assert cat == "sunscreen" and {"hydrating", "spf50"} <= set(tags)
    assert tag_title("rom&nd glasting water tint")[0] == "lip"
    assert strip_html("<b>아누아</b> &amp; 토너") == "아누아 & 토너"


@pytest.mark.anyio
async def test_live_search_filters_olive_young_and_caches():
    live = LiveSearch(FakeNaver(NAVER_ITEMS))
    res = await live.search("아누아 토너", olive_young_only=True)
    assert [p.id for p in res] == ["live:111", "live:333"]          # 쿠팡 listing and zero-price item dropped
    assert res[0].title == "아누아 어성초 77 수딩 토너 250ml" and res[0].mall == "올리브영"
    assert res[0].name == "어성초 77 수딩 토너 250ml" and res[0].brief()["brand"] == "아누아"   # brand not repeated in name
    assert res[0].to_product().rebuy_url == ""                                            # Korean store link ≠ re-buy at home
    assert live.get("live:111") is not None and live.get("live:999") is None
    res_all = await live.search("아누아", olive_young_only=False)
    assert len(res_all) == 3


@pytest.mark.anyio
async def test_disabled_live_search_returns_nothing():
    assert await LiveSearch(None).search("anything") == [] and not LiveSearch(None).enabled


@pytest.mark.anyio
async def test_live_product_works_in_engine_without_home_price(catalog, rules):
    live = LiveSearch(FakeNaver(NAVER_ITEMS))
    (lp, *_) = await live.search("아누아 토너")
    p = lp.to_product()
    assert p.category == "toner" and "heartleaf" in p.tags and p.home_price == {}
    r = scan(p, Profile(currency="USD", skin="sensitive"), [catalog["anua-heartleaf-toner"]], rules)
    assert r.price is None and "home price unknown" in r.evidence[0]       # honest: no home price → no saving claim
    assert r.korea_local == 16.31                                           # 21,900 ÷ 1,343
    assert r.fit.level == "good" and r.duplicates and r.duplicates[0].product_id == "anua-heartleaf-toner"


@pytest.mark.anyio
async def test_summary_mixes_catalog_and_live(catalog, rules):
    live = LiveSearch(FakeNaver(NAVER_ITEMS))
    (lp, *_) = await live.search("아누아 토너")
    basket = Catalog({"boj-relief-sun": catalog["boj-relief-sun"], lp.id: lp.to_product()})
    s = summarize([Line("boj-relief-sun"), Line(lp.id)], basket, Profile(currency="USD"), rules)
    # Korea total 18,000 + 21,900 = 39,900 → ₩1,995 refund (5%) ; home known only for the sunscreen ($18)
    assert s.total_krw == 39900 and s.refund.refund_krw == 1995 and s.home_known_lines == 1
    assert s.home_local == 18.0 and s.lines[1].home_local is None
    # saved claimed only on the known line: 18,000÷1343=13.40 minus its share of refund (1,995×18000/39900=900→$0.67) → 12.73 ; 18−12.73=5.27
    assert s.saved_local == 5.27


def test_unified_search_endpoint_merges_sources(client, monkeypatch):
    import app as appmod
    ctx = appmod.app.state.ctx
    ctx.live = LiveSearch(FakeNaver(NAVER_ITEMS))
    r = client.get("/api/search", params={"q": "아누아 토너"}).json()
    sources = [x["source"] for x in r["results"]]
    assert sources[0] == "catalog" and "live" in sources and r["live_enabled"] is True
    assert client.get("/api/search", params={"q": ""}).status_code == 400
    # pick a live result → detail card → add to list → summary with snapshot
    H = {"X-User-Id": "livetester"}
    client.put("/api/profile", json={"lang": "en", "currency": "USD", "skin": "dry"}, headers=H)
    card = client.post("/api/scan", json={"product_id": "live:333"}, headers=H).json()["card"]
    assert card["source"] == "live" and card["display"]["mall"] == "CJ올리브영" and card["display"]["home"] is None
    assert client.post("/api/list", json={"product_id": "live:333"}, headers=H).json()["items"][0]["source"] == "live"
    ctx.live = LiveSearch(FakeNaver([]))              # cache gone (e.g. server restart) → snapshot keeps it working
    s = client.get("/api/summary", headers=H).json()
    assert s["total_krw"] == 18900 and s["lines"][0]["name"].startswith("[올리브영] 라운드랩") and s["home_known_lines"] == 0
    assert client.post("/api/list", json={"product_id": "live:999"}, headers=H).status_code == 404
