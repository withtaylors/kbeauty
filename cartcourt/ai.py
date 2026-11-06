"""
AI 어댑터 — 딱 두 가지 역할만 맡습니다.
  1) 상품 이미지(또는 캡처)에서 색상·카테고리·상품명·가격 읽기  (vision)
  2) 계산이 끝난 판결을 검사·변호사·판사 말투로 바꾸기             (voice)

판결 내용(무엇을 허가/기각, 어디서 얼마에)은 엔진이 정합니다. AI는 바꿀 수 없습니다.
키가 없으면 규칙 기반 대체(키워드 색상표 + 템플릿 대사)로 동작해 데모가 끊기지 않습니다.
"""
from __future__ import annotations

import base64
import json
import os
import re
from typing import Optional

import httpx

from .engine import PLATFORM_NAMES

ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

# ---------- 규칙 기반 대체 ----------

COLOR_WORDS = {
    "베이지": "#D9C7A3", "아이보리": "#F3EEDC", "크림": "#F2E8CF", "오트밀": "#D6CBB4",
    "화이트": "#F5F5F5", "흰": "#F5F5F5", "블랙": "#111111", "검정": "#111111",
    "그레이": "#8A8A8A", "회색": "#8A8A8A", "차콜": "#3A3A3A", "네이비": "#1F2A44",
    "브라운": "#6B4A2B", "카멜": "#B98A4A", "카키": "#6B6B3A", "올리브": "#6B7A3A",
    "블루": "#3A6FC4", "스카이": "#9DC3E6", "데님": "#4A6A99", "레드": "#B8322A",
    "와인": "#6B2237", "버건디": "#6B2237", "핑크": "#E7A3B8", "퍼플": "#7A5AA6",
    "그린": "#3E7A4E", "민트": "#9FD9C5", "옐로우": "#E8C84A", "머스타드": "#C9A227",
    "오렌지": "#E07A2A", "실버": "#C0C0C0", "골드": "#C9A227",
    # 영문
    "beige": "#D9C7A3", "ivory": "#F3EEDC", "cream": "#F2E8CF", "oatmeal": "#D6CBB4", "white": "#F5F5F5",
    "black": "#111111", "grey": "#8A8A8A", "gray": "#8A8A8A", "charcoal": "#3A3A3A", "navy": "#1F2A44",
    "brown": "#6B4A2B", "camel": "#B98A4A", "khaki": "#6B6B3A", "olive": "#6B7A3A", "blue": "#3A6FC4",
    "sky": "#9DC3E6", "denim": "#4A6A99", "red": "#B8322A", "wine": "#6B2237", "burgundy": "#6B2237",
    "pink": "#E7A3B8", "purple": "#7A5AA6", "green": "#3E7A4E", "mint": "#9FD9C5", "yellow": "#E8C84A",
    "mustard": "#C9A227", "orange": "#E07A2A", "silver": "#C0C0C0", "gold": "#C9A227",
}
CATEGORY_WORDS = {
    "outer": ["코트", "자켓", "재킷", "점퍼", "패딩", "블루종", "트렌치", "무스탕", "아우터", "coat", "jacket", "parka", "puffer", "blouson", "trench"],
    "dress": ["원피스", "드레스", "점프수트", "dress", "jumpsuit"],
    "bag": ["가방", "토트", "숄더", "크로스", "백팩", "클러치", "파우치", "bag", "tote", "backpack", "clutch", "pouch"],
    "shoes": ["신발", "스니커즈", "운동화", "로퍼", "부츠", "샌들", "슬리퍼", "sneaker", "loafer", "boot", "sandal", "slipper", "shoes"],
    "acc": ["모자", "캡", "비니", "양말", "삭스", "목도리", "머플러", "스카프", "벨트", "귀걸이", "목걸이", "반지", "팔찌", "안경", "선글라스", "시계", "장갑",
            "cap", "beanie", "socks", "muffler", "scarf", "belt", "earring", "necklace", "ring", "bracelet", "glasses", "watch", "gloves"],
    "bottom": ["팬츠", "바지", "슬랙스", "데님", "청바지", "스커트", "치마", "쇼츠", "레깅스", "pants", "slacks", "denim", "jeans", "skirt", "shorts", "leggings"],
    "top": ["니트", "스웨터", "가디건", "셔츠", "블라우스", "티셔츠", "맨투맨", "후드", "조끼", "베스트", "knit", "sweater", "cardigan", "shirt", "blouse", "tee", "t-shirt", "hoodie", "sweatshirt", "vest"],
}


def tag_by_keywords(name: str) -> dict:
    n = (name or "")
    nl = n.lower()
    color_hex, color_name = "#808080", ""
    for w, h in COLOR_WORDS.items():
        if w.lower() in nl:
            color_hex, color_name = h, w
            break
    category = "unknown"
    for cat, words in CATEGORY_WORDS.items():
        if any(w.lower() in nl for w in words):
            category = cat
            break
    return {"color_hex": color_hex, "color_name": color_name, "category": category, "source": "keyword"}


# ---------- Vision ----------

VISION_PROMPT = (
    "You are tagging a fashion product image for a shopping tool. Reply ONLY with JSON: "
    '{"name": string|null, "price_krw": integer|null, "category": one of '
    '["top","outer","bottom","dress","bag","shoes","acc","unknown"], '
    '"color_hex": "#RRGGBB" dominant color of the product itself (ignore background and model skin), '
    '"color_name": short Korean color word}. If this is a screenshot of a shop page, read the product name '
    "and the selling price (choose the discounted price if both shown)."
)


async def _image_bytes(image_url: Optional[str] = None, image_b64: Optional[str] = None) -> tuple[bytes, str]:
    if image_b64:
        if "," in image_b64:
            header, data = image_b64.split(",", 1)
            mime = re.search(r"data:(image/[a-z]+)", header)
            return base64.b64decode(data), (mime.group(1) if mime else "image/png")
        return base64.b64decode(image_b64), "image/png"
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
        r = await c.get(image_url, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        return r.content, r.headers.get("content-type", "image/jpeg").split(";")[0]


async def tag_image(image_url: Optional[str] = None, image_b64: Optional[str] = None,
                    fallback_name: str = "") -> dict:
    """이미지에서 색상·카테고리(·상품명·가격). 키가 없으면 키워드 대체."""
    if not (ANTHROPIC_KEY or OPENAI_KEY) or not (image_url or image_b64):
        return tag_by_keywords(fallback_name)
    try:
        data, mime = await _image_bytes(image_url, image_b64)
        b64 = base64.b64encode(data).decode()
        async with httpx.AsyncClient(timeout=40) as c:
            if ANTHROPIC_KEY:
                r = await c.post("https://api.anthropic.com/v1/messages",
                                 headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01",
                                          "content-type": "application/json"},
                                 json={"model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5"),
                                       "max_tokens": 300,
                                       "messages": [{"role": "user", "content": [
                                           {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64}},
                                           {"type": "text", "text": VISION_PROMPT}]}]})
                r.raise_for_status()
                text = r.json()["content"][0]["text"]
            else:
                r = await c.post("https://api.openai.com/v1/chat/completions",
                                 headers={"Authorization": f"Bearer {OPENAI_KEY}"},
                                 json={"model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"), "max_tokens": 300,
                                       "messages": [{"role": "user", "content": [
                                           {"type": "text", "text": VISION_PROMPT},
                                           {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}]}]})
                r.raise_for_status()
                text = r.json()["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", text, re.S)
        out = json.loads(m.group(0)) if m else {}
        kw = tag_by_keywords(out.get("name") or fallback_name)
        return {
            "name": out.get("name"),
            "price": out.get("price_krw"),
            "category": out.get("category") if out.get("category") in CATEGORY_WORDS or out.get("category") == "unknown" else kw["category"],
            "color_hex": out.get("color_hex") if re.fullmatch(r"#?[0-9a-fA-F]{6}", str(out.get("color_hex", ""))) else kw["color_hex"],
            "color_name": out.get("color_name") or kw["color_name"],
            "source": "ai_estimated",
        }
    except Exception as e:
        kw = tag_by_keywords(fallback_name)
        kw["error"] = f"{type(e).__name__}"
        return kw


# ---------- Voice (말투) ----------

def template_voice(verdict: dict, items_by_id: dict) -> dict:
    """키 없이도 동작하는 대사. 숫자는 전부 엔진 결과에서 가져온다."""
    dup = [e for e in verdict["evidence"] if e["rule"] == "R1 중복 판정" and e["result"] == "기각"]
    over = [r for r in verdict["rejected"] if r["reason"].startswith("예산")]
    pros = []
    if dup:
        names = ", ".join(r["item"]["name"] for r in verdict["rejected"] if r["reason"].startswith("중복"))
        pros.append(f"재판장님, {names}은(는) 같은 카테고리에 색상까지 겹칩니다. 명백한 중복 구매입니다.")
    if over:
        pros.append(f"게다가 예산 {verdict['budget']:,}원을 넘기는 피고도 있습니다. " + ", ".join(r["item"]["name"] for r in over) + "은(는) 기각을 구형합니다.")
    if not pros:
        pros.append("중복도 예산 초과도 없군요. 다만 충동구매 여부는 재판장님의 판단에 맡기겠습니다.")
    law = []
    for p in verdict["plan"]:
        if p["discount"]:
            law.append(f"{PLATFORM_NAMES.get(p['platform'], p['platform'])}에서 {p['payment_label']}로 결제하면 {p['discount']:,}원이 할인됩니다. 이보다 나은 조합은 없습니다.")
        else:
            law.append(f"{PLATFORM_NAMES.get(p['platform'], p['platform'])} 장바구니는 적용 가능한 보유 혜택이 없습니다. 표시가 그대로 결제합니다.")
    if not law:
        law.append("변호할 피고가 남지 않았습니다. 이의 없습니다.")
    judge_line = (f"양측 주장을 들었습니다. 중복은 하나만 남기고, 예산 안에서 절약이 가장 큰 조합을 택했습니다. "
                  f"총 {verdict['final_total']:,}원 결제, {verdict['discount']:,}원 할인, 기각 금액 {verdict['rejected_amount']:,}원. 선고합니다.")
    return {"prosecutor": pros, "lawyer": law, "judge": judge_line, "source": "template"}


async def llm_voice(verdict: dict, items_by_id: dict) -> dict:
    base = template_voice(verdict, items_by_id)
    if not (ANTHROPIC_KEY or OPENAI_KEY):
        return base
    prompt = (
        "다음은 쇼핑 장바구니 재판의 '확정된 계산 결과'야. 숫자·상품명·결론은 절대 바꾸지 말고, 말투만 입혀 줘.\n"
        "검사: 깐깐하고 단호. 변호사: 능청스럽고 설득력 있게. 판사: 근엄하고 짧게.\n"
        "JSON으로만 답해: {\"prosecutor\": [문장들], \"lawyer\": [문장들], \"judge\": 문장}\n"
        f"계산 결과: {json.dumps({k: verdict[k] for k in ('orders','plan','discount','final_total','rejected_amount','budget','rejected')}, ensure_ascii=False)}\n"
        f"기본 대사: {json.dumps(base, ensure_ascii=False)}"
    )
    try:
        async with httpx.AsyncClient(timeout=40) as c:
            if ANTHROPIC_KEY:
                r = await c.post("https://api.anthropic.com/v1/messages",
                                 headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01"},
                                 json={"model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5"), "max_tokens": 600,
                                       "messages": [{"role": "user", "content": prompt}]})
                r.raise_for_status()
                text = r.json()["content"][0]["text"]
            else:
                r = await c.post("https://api.openai.com/v1/chat/completions",
                                 headers={"Authorization": f"Bearer {OPENAI_KEY}"},
                                 json={"model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"), "max_tokens": 600,
                                       "messages": [{"role": "user", "content": prompt}]})
                r.raise_for_status()
                text = r.json()["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", text, re.S)
        out = json.loads(m.group(0))
        if isinstance(out.get("prosecutor"), list) and isinstance(out.get("lawyer"), list) and out.get("judge"):
            out["source"] = "llm"
            return out
    except Exception:
        pass
    return base
