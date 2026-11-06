"""
장바구니 재판소 — API 서버
실행: uvicorn app:app --reload --port 8000   →  http://localhost:8000
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import List, Optional

# .env 로드 (python-dotenv 없이)
_env = Path(__file__).parent / ".env"
if _env.exists():
    for line in _env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            if v.strip() and not os.getenv(k.strip()):
                os.environ[k.strip()] = v.strip()

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from cartcourt import ai, scraper, store
from cartcourt.engine import Benefit, Item, Settings, judge

ROOT = Path(__file__).parent
BENEFITS_PATH = ROOT / "cartcourt" / "benefits.json"
SAMPLE_PATH = ROOT / "cartcourt" / "sample_cart.json"

app = FastAPI(title="장바구니 재판소", version="0.2.0")
store.init()


def load_benefits() -> dict:
    return json.loads(BENEFITS_PATH.read_text(encoding="utf-8"))


def current_user(x_user_id: Optional[str] = Header(default=None)) -> str:
    """지금은 기기별 익명 ID(헤더). 로그인 붙이면 이 함수만 세션/토큰 검증으로 바꾸면 됩니다."""
    return store.ensure_user(x_user_id)


# ---------- 모델 ----------

class AddReq(BaseModel):
    url: str

class EnrichReq(BaseModel):
    id: str
    screenshot_b64: Optional[str] = None  # data:image/...;base64,...

class SettingsIn(BaseModel):
    budget: int
    payments: List[str]

class JudgeReq(BaseModel):
    item_ids: Optional[List[str]] = None   # 없으면 장바구니 전체
    budget: Optional[int] = None           # 없으면 저장된 설정


# ---------- 기본 ----------

@app.get("/api/health")
def health():
    return {"ok": True, "ai": bool(ai.ANTHROPIC_KEY or ai.OPENAI_KEY), "benefits_as_of": load_benefits()["as_of"]}


@app.get("/api/benefits")
def benefits():
    return load_benefits()


@app.get("/api/me")
def me(uid: str = Depends(current_user)):
    """앱 시작 시 한 번: 사용자 ID, 설정, 장바구니, 누적 금액."""
    return {"user_id": uid, "settings": store.get_settings(uid), "items": store.list_items(uid), "totals": store.totals(uid)}


# ---------- 설정 ----------

@app.put("/api/settings")
def put_settings(body: SettingsIn, uid: str = Depends(current_user)):
    return store.save_settings(uid, body.budget, body.payments)


# ---------- 장바구니 ----------

@app.get("/api/items")
def get_items(status: str = "active", uid: str = Depends(current_user)):
    return store.list_items(uid, status)


@app.post("/api/items")
async def add_item(req: AddReq, uid: str = Depends(current_user)):
    """링크 하나 추가 → 수집 → 태그 → 저장."""
    data = await scraper.fetch_product(req.url)
    if data.get("ok"):
        tags = await ai.tag_image(image_url=data.get("image"), fallback_name=data.get("name", ""))
        data.update({k: tags[k] for k in ("category", "color_hex", "color_name")})
        data["source"] = "scraped"
    else:
        data.update(ai.tag_by_keywords(data.get("name") or ""))
    data["url"] = req.url
    return store.add_item(uid, data)


@app.post("/api/items/sample")
def add_sample(uid: str = Depends(current_user)):
    for it in json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))["items"]:
        it = dict(it, ok=True, id=None)
        store.add_item(uid, it)
    return store.list_items(uid)


@app.post("/api/items/{iid}/enrich")
async def enrich_item(iid: str, req: EnrichReq, uid: str = Depends(current_user)):
    """증거 보강 수사: 캡처에서 AI가 상품명·가격·색상을 읽어 채움."""
    if not (ai.ANTHROPIC_KEY or ai.OPENAI_KEY):
        raise HTTPException(400, "이미지 AI 키가 없어 캡처를 읽을 수 없습니다 (.env 확인)")
    tags = await ai.tag_image(image_b64=req.screenshot_b64)
    if not (tags.get("name") and tags.get("price")):
        raise HTTPException(422, "캡처에서 상품명·가격을 읽지 못했습니다")
    patch = {"ok": True, "name": tags["name"], "price": int(tags["price"]), "category": tags["category"],
             "color_hex": tags["color_hex"], "color_name": tags.get("color_name", ""), "source": "screenshot",
             "image": (req.screenshot_b64 or "")[:300000], "reason": None}
    out = store.update_item(uid, iid, patch)
    if not out:
        raise HTTPException(404)
    return out


@app.delete("/api/items/{iid}")
def remove_item(iid: str, uid: str = Depends(current_user)):
    return {"ok": store.delete_item(uid, iid)}


@app.delete("/api/items")
def clear_items(uid: str = Depends(current_user)):
    for it in store.list_items(uid):
        store.delete_item(uid, it["id"])
    return {"ok": True}


# ---------- 재판 ----------

@app.post("/api/judge")
async def do_judge(req: JudgeReq, uid: str = Depends(current_user)):
    st = store.get_settings(uid)
    pool = [i for i in store.list_items(uid) if i.get("ok") and i.get("price")]
    if req.item_ids:
        pool = [i for i in pool if i["id"] in set(req.item_ids)]
    if not pool:
        raise HTTPException(400, "재판할 상품이 없습니다")
    data = load_benefits()
    bens = [Benefit(**{k: b[k] for k in ("platform", "payment", "label", "type", "value", "min_amount", "cap", "note")}) for b in data["benefits"]]
    fields = ("id", "name", "platform", "price", "category", "color_hex", "color_name", "url", "image", "source")
    items = [Item(id=i["id"], name=i.get("name") or "이름 없는 상품", platform=i.get("platform") or "unknown",
                  price=int(i["price"]), category=i.get("category") or "unknown",
                  color_hex=i.get("color_hex") or "#808080", color_name=i.get("color_name") or "",
                  url=i.get("url") or "", image=i.get("image") or "", source=i.get("source") or "scraped")
             for i in pool]
    verdict = judge(items, bens, Settings(budget=req.budget or st["budget"], payments=st["payments"]))
    verdict["benefits_as_of"] = data["as_of"]
    verdict["voice"] = await ai.llm_voice(verdict, {i.id: i for i in items})
    verdict["case_no"] = f"2026장바{uuid.uuid4().int % 1000:03d}"
    verdict["defendants"] = [{k: i.get(k) for k in fields} for i in pool]
    verdict["id"] = store.save_verdict(uid, verdict)
    return verdict


@app.get("/api/verdicts")
def verdicts(uid: str = Depends(current_user)):
    return {"verdicts": store.list_verdicts(uid), "totals": store.totals(uid)}


@app.get("/api/verdicts/{vid}")
def verdict_detail(vid: str, uid: str = Depends(current_user)):
    v = store.get_verdict(uid, vid)
    if not v:
        raise HTTPException(404)
    return v


@app.post("/api/verdicts/{vid}/accept")
def accept(vid: str, uid: str = Depends(current_user)):
    r = store.accept_verdict(uid, vid)
    if not r:
        raise HTTPException(404)
    return {**r, "totals": store.totals(uid), "items": store.list_items(uid)}


# ---------- 정적 파일 ----------

app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")
