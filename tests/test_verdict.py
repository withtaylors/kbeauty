"""R5 verdict and live exchange rates — hand-calculated expectations, no network."""
import pytest

from kbeauty.engine import Line, Profile, judge, scan, skin_fit, summarize
from kbeauty.fx import FxSnapshot, LiveFx

USD = Profile(currency="USD", skin="dry")


def test_verdict_buy_here_from_catalog_price(catalog, rules):
    # anua toner: ₩28,000 ÷ 1343 = $20.85 vs home $29 → +28% → buy here
    r = scan(catalog["anua-heartleaf-toner"], USD, [], rules)
    assert r.verdict.kind == "buy_here" and r.verdict.saving_pct == 28 and "cheaper_here" in r.verdict.reasons
    assert r.verdict.decisive and r.evidence[-1].startswith("R5")


def test_verdict_uses_shelf_price_and_flips(catalog, rules):
    from dataclasses import replace
    p = catalog["anua-heartleaf-toner"]
    # shelf says ₩45,000 → $33.51 vs $29 → −16% → buy at home
    r = scan(replace(p, price_krw=45000), USD, [], rules, shelf_price=True)
    assert r.verdict.kind == "buy_home" and r.verdict.saving_pct == -16
    assert "shelf_price_used" in r.verdict.reasons and "[shelf price" in r.evidence[0]
    # ₩37,000 → $27.55 vs $29 → +5% → similar (inside ±10%)
    r = scan(replace(p, price_krw=37000), USD, [], rules, shelf_price=True)
    assert r.verdict.kind == "similar"


def test_verdict_unknown_without_home_price_and_remarks(catalog, rules):
    from dataclasses import replace
    p = replace(catalog["anua-heartleaf-toner"], home_price={})
    r = scan(p, Profile(currency="USD", skin="sensitive"), [catalog["anua-heartleaf-toner"]], rules)
    assert r.verdict.kind == "unknown" and not r.verdict.decisive
    assert "home_price_unknown" in r.verdict.reasons and "already_in_list" in r.verdict.reasons


def test_judge_skin_caution_is_a_remark_not_a_veto(catalog):
    fit = skin_fit(catalog["medicube-zero-pore-pad"], "sensitive")        # BHA + exfoliating on sensitive skin → caution
    assert fit.level == "caution"
    from kbeauty.engine import PriceComparison
    pc = PriceComparison(korea_krw=1, korea_local=10.0, home_local=20.0, saving_local=10.0, saving_pct=50, cheaper_in_korea=True, rule="")
    v = judge(pc, fit, [], shelf_price=False)
    assert v.kind == "buy_here" and "skin_caution" in v.reasons


class FakeFx:
    def __init__(self, snap=None, fail=False):
        self.snap, self.fail, self.calls = snap, fail, 0

    async def latest(self, currencies):
        self.calls += 1
        if self.fail:
            import httpx
            raise httpx.ConnectError("offline")
        return self.snap


@pytest.mark.anyio
async def test_live_fx_applies_and_falls_back(catalog, rules):
    fx = LiveFx(FakeFx(FxSnapshot("2026-11-06", {"USD": 1400.0}, "frankfurter")), ("USD", "JPY"))
    assert fx.apply(rules).fx_krw_per_unit["USD"] == 1343           # nothing fetched yet → file value
    await fx.refresh()
    live = fx.apply(rules)
    assert live.fx_krw_per_unit["USD"] == 1400.0 and live.fx_krw_per_unit["JPY"] == 8.505 and live.as_of == "2026-11-06"
    # engine picks the live rate: ₩28,000 ÷ 1400 = $20.00 → saving $9.00 = 31%
    r = scan(catalog["anua-heartleaf-toner"], USD, [], live)
    assert r.korea_local == 20.0 and r.price.saving_local == 9.0 and r.price.saving_pct == 31
    s = summarize([Line("anua-heartleaf-toner")], catalog, USD, live)
    assert s.fx == 1400.0

    offline = LiveFx(FakeFx(fail=True), ("USD",))
    assert await offline.refresh() is None and offline.apply(rules) is rules       # untouched file rules
    assert LiveFx(None, ("USD",)).stale is False                                   # disabled → never stale


def test_scan_api_returns_verdict_and_accepts_shelf_price(client):
    H = {"X-User-Id": "judge"}
    client.put("/api/profile", json={"lang": "en", "currency": "USD", "skin": "dry"}, headers=H)
    card = client.post("/api/scan", json={"product_id": "anua-heartleaf-toner"}, headers=H).json()["card"]
    assert card["verdict"]["kind"] == "buy_here" and card["display"]["shelf_price"] is False and card["fx"]["source"] == "rules.json"
    card = client.post("/api/scan", json={"product_id": "anua-heartleaf-toner", "shelf_price_krw": 45000}, headers=H).json()["card"]
    assert card["verdict"]["kind"] == "buy_home" and card["display"]["shelf_price"] is True and card["product"]["price_krw"] == 45000
    assert client.post("/api/scan", json={"product_id": "anua-heartleaf-toner", "shelf_price_krw": 5}, headers=H).status_code == 422
    # typed name + shelf price works too
    card = client.post("/api/scan", json={"query": "anua heartleaf toner", "shelf_price_krw": 45000}, headers=H).json()["card"]
    assert card["verdict"]["kind"] == "buy_home"


def test_shelf_price_carries_into_list_and_trip(client):
    """Found by the reviewer: re-judge at ₩45,000 → add → trip must use ₩45,000, not the catalog ₩28,000."""
    H = {"X-User-Id": "shelf"}
    client.put("/api/profile", json={"lang": "en", "currency": "USD", "skin": "dry"}, headers=H)
    lst = client.post("/api/list", json={"product_id": "anua-heartleaf-toner", "shelf_price_krw": 45000}, headers=H).json()
    assert lst["total_krw"] == 45000 and lst["items"][0]["price_krw"] == 45000 and lst["items"][0]["shelf_price"] is True
    s = client.get("/api/summary", headers=H).json()
    assert s["total_krw"] == 45000 and s["refund"]["refund_krw"] == 2250            # 5% band on ₩45,000
    # adding the same product again without a shelf price keeps the stored one; with a new one, updates it
    lst = client.post("/api/list", json={"product_id": "anua-heartleaf-toner"}, headers=H).json()
    assert lst["items"][0]["qty"] == 2 and lst["total_krw"] == 90000
    lst = client.post("/api/list", json={"product_id": "anua-heartleaf-toner", "shelf_price_krw": 30000}, headers=H).json()
    assert lst["items"][0]["qty"] == 3 and lst["total_krw"] == 90000
    # without a shelf price the catalog price is used, as before
    H2 = {"X-User-Id": "noshelf"}
    client.put("/api/profile", json={"lang": "en", "currency": "USD", "skin": "dry"}, headers=H2)
    lst = client.post("/api/list", json={"product_id": "anua-heartleaf-toner"}, headers=H2).json()
    assert lst["total_krw"] == 28000 and lst["items"][0]["shelf_price"] is False
