"""HTTP layer: validation, persistence per user, end-to-end numbers."""
import base64

H = {"X-User-Id": "tourist1"}


def test_profile_validation(client):
    assert client.put("/api/profile", json={"lang": "zh", "currency": "USD", "skin": "dry"}, headers=H).status_code == 422
    assert client.put("/api/profile", json={"lang": "ko", "currency": "JPY", "skin": "sensitive"}, headers=H).status_code == 200
    assert client.get("/api/me", headers=H).json()["profile"]["configured"] is True


def test_scan_requires_exactly_one_input(client):
    assert client.post("/api/scan", json={}, headers=H).status_code == 422
    assert client.post("/api/scan", json={"query": "anua", "product_id": "x"}, headers=H).status_code == 422


def test_search_scan_returns_localized_card(client):
    client.put("/api/profile", json={"lang": "ko", "currency": "JPY", "skin": "sensitive"}, headers=H)
    r = client.post("/api/scan", json={"query": "anua heartleaf toner"}, headers=H).json()
    assert r["status"] == "ok" and r["card"]["product"]["id"] == "anua-heartleaf-toner"
    assert "어성초" in r["card"]["display"]["tags"] and r["card"]["fit"]["level"] == "good"


def test_ambiguous_search_offers_candidates(client):
    r = client.post("/api/scan", json={"query": "torriden"}, headers=H).json()
    assert r["status"] == "choose" and {x["id"] for x in r["candidates"]} >= {"torriden-divein-serum", "torriden-soothing-cream"}


def test_photo_without_vision_key_falls_back(client):
    img = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff").decode()
    r = client.post("/api/scan", json={"image_b64": img}, headers=H).json()
    assert r["status"] == "fallback" and r["method"] == "no_ai"


def test_invalid_image_is_422(client):
    assert client.post("/api/scan", json={"image_b64": "data:image/png;base64,@@@"}, headers=H).status_code == 422


def test_duplicate_warning_after_adding(client):
    client.post("/api/list", json={"product_id": "torriden-divein-serum"}, headers=H)
    r = client.post("/api/scan", json={"product_id": "innisfree-greentea-serum"}, headers=H).json()
    d = r["card"]["display"]["duplicates"]
    assert len(d) == 1 and d[0]["id"] == "torriden-divein-serum" and d[0]["same"] is False


def test_list_persists_per_user_and_summary_matches_hand_calc(client):
    client.put("/api/profile", json={"lang": "en", "currency": "USD", "skin": "dry"}, headers=H)
    for pid in ("anua-heartleaf-toner", "torriden-divein-serum", "boj-relief-sun"):
        client.post("/api/list", json={"product_id": pid}, headers=H)
    client.post("/api/list", json={"product_id": "boj-relief-sun"}, headers=H)   # same item → qty 2
    lst = client.get("/api/list", headers=H).json()
    assert len(lst["items"]) == 3 and next(i["qty"] for i in lst["items"] if i["product_id"] == "boj-relief-sun") == 2
    item = next(i for i in lst["items"] if i["product_id"] == "boj-relief-sun")
    client.put(f"/api/list/{item['id']}", json={"qty": 1}, headers=H)
    s = client.get("/api/summary", headers=H).json()
    assert s["total_krw"] == 68000 and s["refund"]["refund_krw"] == 4420 and s["saved_local"] == 21.66
    assert client.get("/api/list", headers={"X-User-Id": "someoneelse"}).json()["items"] == []
    assert client.get("/api/summary", headers={"X-User-Id": "someoneelse"}).status_code == 400


def test_unknown_product_404(client):
    assert client.post("/api/list", json={"product_id": "nope"}, headers=H).status_code == 404
    assert client.post("/api/scan", json={"product_id": "nope"}, headers=H).status_code == 404


def test_product_requests_flow(client, tmp_path, monkeypatch):
    """User asks for a missing product → reviewer approves via manage.py → user sees the catalog product."""
    import manage
    H = {"X-User-Id": "requester"}
    r = client.post("/api/requests", json={"name": "Heroine Make Smooth Liquid Eyeliner", "brand": "KissMe", "note": "black, waterproof"}, headers=H)
    assert r.status_code == 201 and r.json()["status"] == "pending"
    rid = r.json()["id"]
    assert client.post("/api/requests", json={"name": "x"}, headers=H).status_code == 422       # too short
    assert client.get("/api/requests", headers=H).json()["requests"][0]["id"] == rid
    assert client.get("/api/requests", headers={"X-User-Id": "someone-else"}).json()["requests"] == []   # private

    ctx = client.app.state.ctx
    monkeypatch.setattr(manage, "get_settings", lambda: ctx.settings)
    import pytest as _pt
    with _pt.raises(SystemExit):                                   # cannot approve with an id that is not in products.json
        manage.main(["approve", rid, "not-a-product"])
    manage.main(["approve", rid, "anua-heartleaf-toner", "--note", "added 11/06"])
    mine = client.get("/api/requests", headers=H).json()["requests"][0]
    assert mine["status"] == "approved" and mine["admin_note"] == "added 11/06" and mine["product"]["id"] == "anua-heartleaf-toner"

    rid2 = client.post("/api/requests", json={"name": "Some discontinued cream"}, headers=H).json()["id"]
    manage.main(["reject", rid2, "--note", "discontinued"])
    assert [x["status"] for x in client.get("/api/requests", headers=H).json()["requests"]] == ["rejected", "approved"]
