"""Web home price — extraction rules and the end-to-end 'judge any product' flow, with a fake search client."""
import httpx
import pytest

from kbeauty.webprice import WebPriceFinder, extract

# Shape of real Tavily results (title/url/content).  Korea price $20.82 → accepted band $10.41–$83.28.
RESULTS = [
    {"title": "Anua Heartleaf 77% Soothing Toner 250ml", "url": "https://www.amazon.com/anua-toner",
     "content": "Anua Heartleaf 77% Soothing Toner 250ml. Price: $29.00. Free shipping over $35."},
    {"title": "ANUA Heartleaf 77 Soothing Toner | Ulta", "url": "https://www.ulta.com/p/anua",
     "content": "Heartleaf 77% Soothing Toner by Anua — $27.00"},
    {"title": "Anua Heartleaf 77% Soothing Toner", "url": "https://www.yesstyle.com/en/anua",
     "content": "Anua Heartleaf 77% Soothing Toner 250ml US$ 31.50 on sale"},
    {"title": "Anua 어성초 77 토너", "url": "https://www.oliveyoung.co.kr/x",            # Korean site → ignored
     "content": "Anua heartleaf soothing toner $20.00"},
    {"title": "Anua Heartleaf 77% Soothing Toner sample", "url": "https://deals.example.com/a",
     "content": "Anua Heartleaf 77% Soothing Toner mini $3.99"},                         # below band → ignored
    {"title": "Best toners 2026", "url": "https://blog.example.com/b",
     "content": "Our favourite toners: $19 and up"},                                      # not this product → ignored
    {"title": "Anua Heartleaf 77% Soothing Toner", "url": "https://www.amazon.com/dup",
     "content": "Anua Heartleaf 77% Soothing Toner $45.00"},                              # same domain twice → first kept
]


class FakeSearch:
    def __init__(self, results=None, fail=False):
        self.results, self.fail, self.calls = results or [], fail, []

    async def search(self, query, country, max_results):
        self.calls.append((query, country))
        if self.fail:
            raise httpx.ConnectError("offline")
        return self.results


def test_extract_keeps_only_matching_foreign_in_band_one_per_domain():
    got = extract(RESULTS, "USD", "Anua", "Heartleaf 77% Soothing Toner", korea_local=20.82)
    assert [(s.domain, s.price) for s in got] == [("amazon.com", 29.0), ("ulta.com", 27.0), ("yesstyle.com", 31.5)]


def test_extract_jpy_patterns():
    rs = [{"title": "Anua ドクダミ77 スージングトナー Heartleaf Toner", "url": "https://www.amazon.co.jp/a",
           "content": "Anua Heartleaf Toner ￥3,190 税込"},
          {"title": "Anua Heartleaf Toner", "url": "https://item.rakuten.co.jp/b", "content": "Anua Heartleaf Toner 2,980円"}]
    got = extract(rs, "JPY", "Anua", "Heartleaf Toner", korea_local=3300)
    assert [s.price for s in got] == [3190.0, 2980.0]


@pytest.mark.anyio
async def test_lookup_median_cache_and_minimum_sources():
    fake = FakeSearch(RESULTS)
    f = WebPriceFinder(fake)
    wp = await f.lookup("Anua", "Heartleaf 77% Soothing Toner", "USD", 20.82)
    assert wp.price == 29.0 and len(wp.sources) == 3                      # median of 27, 29, 31.5
    assert fake.calls == [("Anua Heartleaf 77% Soothing Toner price", "united states")]
    await f.lookup("Anua", "Heartleaf 77% Soothing Toner", "USD", 20.82)
    assert len(fake.calls) == 1                                           # cached

    one = WebPriceFinder(FakeSearch(RESULTS[:1]))                         # a single source is not enough
    assert await one.lookup("Anua", "Heartleaf 77% Soothing Toner", "USD", 20.82) is None
    assert await WebPriceFinder(FakeSearch(fail=True)).lookup("Anua", "x y z", "USD", 20) is None
    assert await WebPriceFinder(None).lookup("Anua", "x", "USD", 20) is None


def test_judge_any_product_uses_web_price_and_flows_into_trip(client):
    import app as appmod
    ctx = appmod.app.state.ctx
    H = {"X-User-Id": "webjudge"}
    client.put("/api/profile", json={"lang": "en", "currency": "USD", "skin": "dry"}, headers=H)

    # web search off → honest "ruling deferred"
    r = client.post("/api/judge", json={"name": "Anua Heartleaf 77% Soothing Toner", "shelf_price_krw": 28000}, headers=H).json()
    assert r["card"]["verdict"]["kind"] == "unknown" and r["web_price_enabled"] is False

    # web search on → $29 from 3 sources; ₩28,000 ÷ 1343 = $20.85 → (29−20.85)/29 = 28% → buy here
    ctx.webprice = WebPriceFinder(FakeSearch(RESULTS))
    card = client.post("/api/judge", json={"name": "Anua Heartleaf 77% Soothing Toner", "shelf_price_krw": 28000}, headers=H).json()["card"]
    assert card["source"] == "manual" and card["verdict"]["kind"] == "buy_here" and card["verdict"]["saving_pct"] == 28
    assert card["home_source"]["kind"] == "web" and len(card["home_source"]["sources"]) == 3
    assert card["product"]["category"] == "toner"                       # tagged from the typed name

    # add to list → trip uses the shelf price and the web home price
    lst = client.post("/api/list", json={"product_id": card["product"]["id"]}, headers=H).json()
    assert lst["total_krw"] == 28000 and lst["items"][0]["source"] == "manual"
    s = client.get("/api/summary", headers=H).json()
    assert s["home_known_lines"] == 1 and s["home_local"] == 29.0

    # catalog products keep their curated home price — the web is never consulted for them
    calls = len(ctx.webprice._client.calls)
    client.post("/api/scan", json={"product_id": "anua-heartleaf-toner"}, headers=H)
    assert len(ctx.webprice._client.calls) == calls
    assert client.post("/api/judge", json={"name": "x", "shelf_price_krw": 5000}, headers=H).status_code == 422


def test_description_reads_well_without_brand_or_tags():
    from kbeauty.catalog import Product
    from kbeauty.i18n import describe
    p = Product(id="web:x", brand_en="", brand_ko="", name_en="Some Serum", name_ko="Some Serum", category="serum",
                tags=(), size="", price_krw=10000, home_price={}, rebuy_url="", image="")
    assert describe(p, "ko") == "세럼·에센스입니다." and describe(p, "en").startswith("A serum")
