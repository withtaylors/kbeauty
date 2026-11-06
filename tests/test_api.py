import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["CARTCOURT_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")

from fastapi.testclient import TestClient
import app as appmod

c = TestClient(appmod.app)
A = {"X-User-Id": "user-a"}
B = {"X-User-Id": "user-b"}


def test_cart_persists_and_is_per_user():
    c.put("/api/settings", json={"budget": 200000, "payments": ["shinhan", "naverpay"]}, headers=A)
    c.post("/api/items/sample", headers=A)
    me = c.get("/api/me", headers=A).json()
    assert len(me["items"]) == 5 and me["settings"]["payments"] == ["shinhan", "naverpay"]
    # 다른 사용자에게는 보이지 않음
    assert c.get("/api/me", headers=B).json()["items"] == []
    # 같은 링크를 다시 넣으면 새로 쌓이지 않고 갱신됨
    c.post("/api/items/sample", headers=A)
    assert len(c.get("/api/items", headers=A).json()) == 5


def test_judge_saves_history_and_execute_counts_once():
    v = c.post("/api/judge", json={}, headers=A).json()
    assert v["id"] and v["rejected_amount"] > 0
    v2 = c.post("/api/judge", json={}, headers=A).json()           # 재심 (같은 장바구니)
    hist = c.get("/api/verdicts", headers=A).json()
    assert len(hist["verdicts"]) == 2
    assert hist["totals"]["saved"] == 0                             # 집행 전에는 누적 0
    r = c.post(f"/api/verdicts/{v2['id']}/accept", headers=A).json()
    assert r["totals"]["saved"] == v2["discount"] + v2["rejected_amount"]
    r2 = c.post(f"/api/verdicts/{v2['id']}/accept", headers=A).json()
    assert r2["already"] and r2["totals"]["saved"] == r["totals"]["saved"]   # 중복 집계 없음
    assert c.get("/api/items", headers=A).json() == []              # 허가→구매, 기각→취하로 장바구니 비워짐
    assert len(c.get("/api/items?status=dropped", headers=A).json()) == len(v2["rejected"])
    # 판결 다시 보기
    assert c.get(f"/api/verdicts/{v['id']}", headers=A).json()["case_no"] == v["case_no"]
    assert c.get(f"/api/verdicts/{v['id']}", headers=B).status_code == 404   # 남의 판결은 못 봄


def test_delete_item():
    c.post("/api/items/sample", headers=B)
    items = c.get("/api/items", headers=B).json()
    c.delete(f"/api/items/{items[0]['id']}", headers=B)
    assert len(c.get("/api/items", headers=B).json()) == len(items) - 1
