"""
장바구니 재판소 판결 엔진 (순수 함수, 결정론적)

AI는 여기 없습니다. 같은 입력이면 항상 같은 판결이 나옵니다.
  1. 중복 판정  : 같은 카테고리 + 색상 거리 < 기준 → 하나의 '중복 묶음'
  2. 가격·혜택  : 플랫폼별 표시가 - 보유 결제수단 혜택 → 최종가
  3. 최적 조합  : 예산 안에서 '절약액 최대'(동률이면 총액 최소) 조합 선택
  4. 출력       : 허가/기각 목록, 플랫폼·결제수단, 절약액, 기각 금액, 근거표
"""
from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

PLATFORM_NAMES = {"musinsa": "무신사", "29cm": "29CM", "zigzag": "지그재그", "coupang": "쿠팡", "ably": "에이블리"}
COLOR_THRESHOLD = 0.18          # 0~1 정규화된 RGB 거리. 이하면 '비슷한 색'
MAX_ITEMS_FOR_EXACT = 12        # 이 개수까지 전수조사(2^n). 넘으면 탐욕법


# ---------- 데이터 ----------

@dataclass
class Item:
    id: str
    name: str
    platform: str                # musinsa | 29cm | zigzag | coupang | ...
    price: int                   # 표시가 (원)
    category: str = "unknown"    # top | bottom | outer | bag | shoes | acc | unknown
    color_hex: str = "#808080"   # 대표 색
    color_name: str = ""
    url: str = ""
    image: str = ""
    source: str = "scraped"      # scraped | ai_estimated | screenshot
    flag: bool = False           # 정상참작 요청 (이후 확장)


@dataclass
class Benefit:
    platform: str
    payment: str                 # 카드/간편결제 id
    label: str                   # 사람이 읽는 이름
    type: str                    # percent | fixed
    value: float                 # percent면 10 → 10%, fixed면 원
    min_amount: int = 0          # 결제 금액 조건
    cap: int = 0                 # 할인 상한 (0이면 없음)
    note: str = ""


@dataclass
class Settings:
    budget: int
    payments: List[str]          # 보유 결제수단 id 목록
    color_threshold: float = COLOR_THRESHOLD


# ---------- 유틸 ----------

def hex_to_rgb(h: str) -> Tuple[float, float, float]:
    h = (h or "#808080").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore
    except ValueError:
        return (0.5, 0.5, 0.5)


def color_distance(a: str, b: str) -> float:
    """0(같음) ~ 1(정반대). 사람 눈 가중치(R0.3 G0.59 B0.11)를 적용한 유클리드 거리."""
    r1, g1, b1 = hex_to_rgb(a)
    r2, g2, b2 = hex_to_rgb(b)
    d = math.sqrt(0.30 * (r1 - r2) ** 2 + 0.59 * (g1 - g2) ** 2 + 0.11 * (b1 - b2) ** 2)
    return round(d, 4)


def won(n: float) -> int:
    return int(round(n))


# ---------- 1. 중복 묶음 ----------

def group_duplicates(items: List[Item], threshold: float = COLOR_THRESHOLD) -> List[List[Item]]:
    """같은 카테고리이고 색상 거리가 threshold 이하인 상품끼리 묶는다 (union-find)."""
    parent = {it.id: it.id for it in items}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in itertools.combinations(items, 2):
        if a.category == b.category and a.category != "unknown" \
                and color_distance(a.color_hex, b.color_hex) <= threshold:
            parent[find(a.id)] = find(b.id)

    groups: Dict[str, List[Item]] = {}
    for it in items:
        groups.setdefault(find(it.id), []).append(it)
    # 입력 순서를 유지해 결정론 보장
    order = {it.id: i for i, it in enumerate(items)}
    return sorted(groups.values(), key=lambda g: min(order[i.id] for i in g))


# ---------- 2. 혜택 계산 ----------

def benefit_discount(amount: int, b: Benefit) -> int:
    if amount < b.min_amount:
        return 0
    disc = amount * b.value / 100 if b.type == "percent" else b.value
    if b.cap:
        disc = min(disc, b.cap)
    return won(min(disc, amount))


def best_payment_for_basket(platform: str, amount: int, benefits: List[Benefit],
                            owned: List[str]) -> Tuple[Optional[Benefit], int]:
    """플랫폼 장바구니 금액에 대해 보유 결제수단 중 할인이 가장 큰 것."""
    best, best_disc = None, 0
    for b in sorted(benefits, key=lambda x: x.payment):     # 정렬: 동률 시 결정론
        if b.platform != platform or b.payment not in owned:
            continue
        d = benefit_discount(amount, b)
        if d > best_disc:
            best, best_disc = b, d
    return best, best_disc


def evaluate_combination(chosen: List[Item], benefits: List[Benefit], owned: List[str]):
    """선택한 상품 집합의 플랫폼별 장바구니 → 결제수단 → 총액/절약액."""
    baskets: Dict[str, List[Item]] = {}
    for it in chosen:
        baskets.setdefault(it.platform, []).append(it)
    plan, total_list, total_disc = [], 0, 0
    for platform in sorted(baskets):
        items = baskets[platform]
        amount = sum(i.price for i in items)
        b, disc = best_payment_for_basket(platform, amount, benefits, owned)
        plan.append({
            "platform": platform,
            "items": [i.id for i in items],
            "list_total": amount,
            "payment": b.payment if b else None,
            "payment_label": b.label if b else "혜택 없음",
            "discount": disc,
            "final_total": amount - disc,
            "rule": (f"{b.label}: {b.value:g}% 할인" + (f" (최대 {b.cap:,}원)" if b.cap else "")
                     if b and b.type == "percent" else
                     f"{b.label}: {b.value:,.0f}원 할인" if b else "적용 가능한 보유 혜택 없음")
                    + (f", {b.min_amount:,}원 이상 결제 시" if b and b.min_amount else ""),
        })
        total_list += amount
        total_disc += disc
    return plan, total_list, total_disc, total_list - total_disc


# ---------- 3. 최적 조합 ----------

def choose_best_subset(candidates: List[Item], benefits: List[Benefit], settings: Settings):
    """예산 안에서 절약액 최대. 동률이면 (상품 수 많음 → 총액 적음) 순."""
    owned = settings.payments
    n = len(candidates)
    best = None
    if n <= MAX_ITEMS_FOR_EXACT:
        for r in range(n, -1, -1):
            for combo in itertools.combinations(candidates, r):
                plan, lst, disc, final = evaluate_combination(list(combo), benefits, owned)
                if final > settings.budget:
                    continue
                key = (disc, len(combo), -final)
                if best is None or key > best[0]:
                    best = (key, list(combo), plan, lst, disc, final)
    else:  # 탐욕: 단가 낮은 순으로 예산에 들어가는 만큼
        chosen = []
        for it in sorted(candidates, key=lambda i: (i.price, i.id)):
            trial = chosen + [it]
            _, _, _, final = evaluate_combination(trial, benefits, owned)
            if final <= settings.budget:
                chosen = trial
        plan, lst, disc, final = evaluate_combination(chosen, benefits, owned)
        best = ((disc, len(chosen), -final), chosen, plan, lst, disc, final)
    _, chosen, plan, lst, disc, final = best
    return chosen, plan, lst, disc, final


# ---------- 4. 판결 ----------

def judge(items: List[Item], benefits: List[Benefit], settings: Settings) -> dict:
    owned = settings.payments
    evidence: List[dict] = []
    rejected: List[dict] = []

    # 1) 중복 묶음 → 묶음당 하나(개별 최종가 최저) 생존
    groups = group_duplicates(items, settings.color_threshold)
    survivors: List[Item] = []
    for g in groups:
        if len(g) == 1:
            survivors.append(g[0])
            continue
        scored = []
        for it in g:
            b, d = best_payment_for_basket(it.platform, it.price, benefits, owned)
            scored.append((it.price - d, it.price, it.id, it, b, d))
        scored.sort()
        winner = scored[0][3]
        survivors.append(winner)
        names = ", ".join(i.name for i in g)
        for final, price, _, it, b, d in scored:
            evidence.append({
                "rule": "R1 중복 판정",
                "item": it.name,
                "detail": f"{it.category} / 색 {it.color_hex} → 묶음 [{names}] 중 "
                          f"최종가 {final:,}원 ({it.platform} {price:,}원"
                          + (f" − {b.label} {d:,}원" if b else "") + ")",
                "result": "생존" if it is winner else "기각",
            })
            if it is not winner:
                dist = color_distance(it.color_hex, winner.color_hex)
                rejected.append({"item": it, "reason": f"중복: {winner.name}과 색상 거리 {dist} ≤ {settings.color_threshold}, 최종가 {final:,}원 > {scored[0][0]:,}원"})

    # 2) 예산 내 최적 조합
    chosen, plan, list_total, discount, final_total = choose_best_subset(survivors, benefits, settings)
    chosen_ids = {i.id for i in chosen}
    for it in survivors:
        if it.id not in chosen_ids:
            rejected.append({"item": it, "reason": f"예산 초과: 포함 시 예산 {settings.budget:,}원 안에서 절약 최대 조합에 들지 못함"})

    for p in plan:
        evidence.append({
            "rule": "R2 가격·혜택",
            "item": f"{p['platform']} 장바구니",
            "detail": f"표시가 합 {p['list_total']:,}원 − {p['rule']} → 최종 {p['final_total']:,}원",
            "result": f"−{p['discount']:,}원",
        })
    evidence.append({
        "rule": "R3 예산·조합",
        "item": f"생존 {len(survivors)}개 중 {len(chosen)}개 선택",
        "detail": f"예산 {settings.budget:,}원 이내 조합 전수 비교 → 절약 최대 {discount:,}원 (총 {final_total:,}원)",
        "result": "채택",
    })

    # 3) 소수의견: 미보유 결제수단이 더 이득이면
    minority = None
    all_payments = sorted({b.payment for b in benefits})
    _, _, disc_all, final_all = evaluate_combination(chosen, benefits, all_payments)
    if disc_all > discount:
        alt_plan, _, _, _ = evaluate_combination(chosen, benefits, all_payments)
        labels = sorted({p["payment_label"] for p in alt_plan if p["payment"] and p["payment"] not in owned})
        minority = f"{', '.join(labels)}를 보유했다면 {disc_all - discount:,}원을 더 아낄 수 있었음"

    rejected_amount = sum(r["item"].price for r in rejected)
    orders = []
    for i, it in enumerate(chosen, 1):
        pl = next(p for p in plan if it.id in p["items"])
        with_items = [x for x in pl["items"] if x != it.id]
        together = (" " + "·".join(next(c.name for c in chosen if c.id == w) for w in with_items) + "과 함께") if with_items else ""
        pay = f"{pl['payment_label']}로 결제한다." if pl["payment"] else "결제한다 (적용 혜택 없음)."
        orders.append(f"피고 {it.name}의 구매를 허가한다. {PLATFORM_NAMES.get(it.platform, it.platform)}에서{together} {pay}")
    for r in rejected:
        orders.append(f"피고 {r['item'].name}에 대한 구매 청구는 기각한다.")

    return {
        "approved": [asdict(i) for i in chosen],
        "rejected": [{"item": asdict(r["item"]), "reason": r["reason"]} for r in rejected],
        "plan": plan,
        "list_total": list_total,
        "discount": discount,
        "final_total": final_total,
        "budget": settings.budget,
        "rejected_amount": rejected_amount,
        "saved_total": discount + rejected_amount,
        "orders": orders,
        "evidence": evidence,
        "minority_opinion": minority,
        "groups": [[i.id for i in g] for g in groups],
    }
