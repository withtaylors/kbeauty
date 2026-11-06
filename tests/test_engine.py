import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cartcourt.engine import (Item, Benefit, Settings, judge, group_duplicates,
                              color_distance, benefit_discount, evaluate_combination)

BENEFITS = [
    Benefit("29cm", "shinhan", "신한카드", "percent", 10, min_amount=50000, cap=10000),
    Benefit("29cm", "naverpay", "네이버페이", "percent", 3),
    Benefit("musinsa", "naverpay", "네이버페이", "percent", 5, cap=5000),
    Benefit("musinsa", "hyundai", "현대카드", "percent", 15, min_amount=100000, cap=20000),
]

def knit(i, platform, price, hexc="#D9C7A3"):
    return Item(id=i, name=f"베이지 니트 {i}", platform=platform, price=price,
                category="top", color_hex=hexc)

def test_color_distance_symmetric_and_bounded():
    assert color_distance("#000000", "#000000") == 0
    assert 0.99 <= color_distance("#000000", "#ffffff") <= 1
    assert color_distance("#D9C7A3", "#E0CFAE") < 0.18       # 두 베이지
    assert color_distance("#D9C7A3", "#111111") > 0.18       # 베이지 vs 블랙

def test_duplicate_grouping():
    items = [knit("A", "musinsa", 59000), knit("B", "29cm", 55000, "#E0CFAE"),
             knit("C", "zigzag", 52000, "#DCC9A8"),
             Item("bag", "블랙 가방", "29cm", 89000, "bag", "#111111")]
    groups = group_duplicates(items)
    assert len(groups) == 2
    assert sorted(len(g) for g in groups) == [1, 3]

def test_benefit_discount_rules():
    b = Benefit("29cm", "shinhan", "신한", "percent", 10, min_amount=50000, cap=10000)
    assert benefit_discount(40000, b) == 0          # 조건 미달
    assert benefit_discount(80000, b) == 8000
    assert benefit_discount(200000, b) == 10000     # 상한

def test_verdict_example_from_proposal():
    """기획안 예시: 니트 3벌 중 B만 허가, 29CM에서 가방과 함께 신한카드."""
    items = [knit("A", "musinsa", 59000), knit("B", "29cm", 55000, "#E0CFAE"),
             knit("C", "zigzag", 52000, "#DCC9A8"),
             Item("bag", "블랙 가방", "29cm", 89000, "bag", "#111111")]
    s = Settings(budget=200000, payments=["shinhan", "naverpay"])
    v = judge(items, BENEFITS, s)
    approved = {i["id"] for i in v["approved"]}
    # 중복 묶음에서 개별 최종가 최저는 C(52,000, 지그재그는 혜택 없음) → C 생존
    # 하지만 B는 29CM 신한 10%로 49,500 → B가 최저. 따라서 B 생존
    assert "B" in approved and "A" not in approved and "C" not in approved
    assert "bag" in approved
    plan29 = next(p for p in v["plan"] if p["platform"] == "29cm")
    assert plan29["payment"] == "shinhan"
    assert plan29["list_total"] == 144000 and plan29["discount"] == 10000
    assert v["final_total"] == 134000
    assert v["rejected_amount"] == 59000 + 52000
    assert any(r["rule"] == "R1 중복 판정" for r in v["evidence"])

def test_budget_rejects_and_is_deterministic():
    items = [Item("x", "코트", "musinsa", 150000, "outer", "#333333"),
             Item("y", "셔츠", "29cm", 40000, "top", "#ffffff")]
    s = Settings(budget=100000, payments=["naverpay"])
    v1 = judge(items, BENEFITS, s)
    v2 = judge(items, BENEFITS, s)
    assert v1 == v2                                   # 결정론
    assert [i["id"] for i in v1["approved"]] == ["y"]
    assert v1["rejected"][0]["item"]["id"] == "x"
    assert "예산 초과" in v1["rejected"][0]["reason"]

def test_minority_opinion_when_unowned_card_is_better():
    items = [Item("x", "코트", "musinsa", 150000, "outer", "#333333")]
    s = Settings(budget=200000, payments=["naverpay"])
    v = judge(items, BENEFITS, s)
    assert v["discount"] == 5000
    assert v["minority_opinion"] and "현대카드" in v["minority_opinion"]

def test_evaluate_combination_prefers_bundle_threshold():
    items = [Item("a", "A", "29cm", 30000, "top", "#000"), Item("b", "B", "29cm", 30000, "bag", "#fff")]
    _, lst, disc, final = evaluate_combination(items, BENEFITS, ["shinhan", "naverpay"])
    assert lst == 60000 and disc == 6000 and final == 54000   # 합산 5만 이상 → 신한 10%
