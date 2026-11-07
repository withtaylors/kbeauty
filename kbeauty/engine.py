"""
Deterministic pricing engine — no AI here.  Same input → same output, every time.

    R1  price comparison   KRW → home currency, vs. home reference price
    R2  skin fit           ingredient tags × skin-type rule table
    R3  duplicate check    same category + ≥ N shared tags with an item already in the list
    R4  tax refund         per-store transaction total ≥ threshold → banded refund rate

Every result carries an `evidence` line so the UI can show exactly how a number was produced.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from typing import Literal

from .catalog import Catalog, Currency, Product, Rules

CURRENCY_SYMBOL = {"USD": "$", "JPY": "¥", "CNY": "¥", "KRW": "₩"}
CURRENCY_DECIMALS = {"USD": 2, "JPY": 0, "CNY": 1, "KRW": 0}

SkinType = Literal["dry", "oily", "combination", "sensitive"]
FitLevel = Literal["good", "ok", "caution"]

# Tag → skin-type scoring table.  "+" helps, "-" warrants caution.  This table *is* the rule;
# it is intentionally explicit so a reviewer can audit every verdict.
SKIN_RULES: dict[str, dict[str, frozenset[str]]] = {
    "dry":         {"+": frozenset({"hydrating", "ceramide", "barrier", "hyaluronic_acid", "snail_mucin", "overnight", "collagen", "oil_cleanse", "glow"}),
                    "-": frozenset({"bha", "oil_control", "matte", "exfoliating"})},
    "oily":        {"+": frozenset({"bha", "oil_control", "pore_care", "tea_tree", "niacinamide", "matte", "low_ph", "oil_cleanse"}),
                    "-": frozenset({"overnight", "ceramide"})},
    "combination": {"+": frozenset({"hyaluronic_acid", "pore_care", "niacinamide", "low_ph", "panthenol", "hydrating"}),
                    "-": frozenset()},
    "sensitive":   {"+": frozenset({"soothing", "centella", "heartleaf", "panthenol", "fragrance_free", "low_ph", "barrier", "ceramide", "cica"}),
                    "-": frozenset({"exfoliating", "bha", "vitamin_c", "microneedle", "tea_tree"})},
}
MAKEUP_CATEGORIES = frozenset({"lip", "cushion", "blush"})   # skin-fit rules do not apply


# ---------- helpers ----------

def round_money(amount: float, cur: Currency) -> float:
    d = CURRENCY_DECIMALS.get(cur, 2)
    return float(round(amount, d)) if d else float(round(amount))


def money(amount: float, cur: Currency) -> str:
    d = CURRENCY_DECIMALS.get(cur, 2)
    body = f"{amount:,.{d}f}" if d else f"{round(amount):,}"
    return f"{CURRENCY_SYMBOL.get(cur, '')}{body}"


def krw_to(krw: float, cur: Currency, rules: Rules) -> float:
    if cur == "KRW":
        return float(krw)
    return round_money(krw / rules.fx_krw_per_unit[cur], cur)


# ---------- R1 ----------

@dataclass(frozen=True)
class PriceComparison:
    korea_krw: int
    korea_local: float
    home_local: float
    saving_local: float
    saving_pct: int
    cheaper_in_korea: bool
    rule: str


def compare_price(product: Product, cur: Currency, rules: Rules) -> PriceComparison | None:
    """None when the home-country price is unknown (live listings) — never a guess."""
    korea_local = krw_to(product.price_krw, cur, rules)
    if cur not in product.home_price:
        return None
    home = product.home_price[cur]
    saving = round_money(home - korea_local, cur)
    pct = round(saving / home * 100) if home else 0
    return PriceComparison(
        korea_krw=product.price_krw, korea_local=korea_local, home_local=home,
        saving_local=saving, saving_pct=pct, cheaper_in_korea=saving > 0,
        rule=f"R1: ₩{product.price_krw:,} ÷ {rules.fx_krw_per_unit[cur]:g} = {money(korea_local, cur)} vs home {money(home, cur)}",
    )


# ---------- R2 ----------

@dataclass(frozen=True)
class SkinFit:
    level: FitLevel
    good: tuple[str, ...]
    caution: tuple[str, ...]
    rule: str


def skin_fit(product: Product, skin: str) -> SkinFit:
    if product.category in MAKEUP_CATEGORIES or skin not in SKIN_RULES:
        return SkinFit("ok", (), (), "R2: makeup / neutral")
    tags = frozenset(product.tags)
    good = tuple(sorted(tags & SKIN_RULES[skin]["+"]))
    bad = tuple(sorted(tags & SKIN_RULES[skin]["-"]))
    score = len(good) - len(bad)
    level: FitLevel = "good" if score >= 1 and not bad else "caution" if bad and score <= 0 else "ok"
    return SkinFit(level, good, bad, f"R2: +{len(good)} −{len(bad)} → {level}")


# ---------- R3 ----------

@dataclass(frozen=True)
class Duplicate:
    product_id: str
    shared_tags: tuple[str, ...]
    same_product: bool


def find_duplicates(product: Product, basket: Iterable[Product], min_shared: int = 2) -> list[Duplicate]:
    hits: list[Duplicate] = []
    for other in basket:
        if other.id == product.id:
            hits.append(Duplicate(other.id, product.tags, True))
            continue
        if other.category != product.category:
            continue
        shared = tuple(sorted(set(product.tags) & set(other.tags)))
        if len(shared) >= min_shared:
            hits.append(Duplicate(other.id, shared, False))
    return hits


# ---------- R4 ----------

@dataclass(frozen=True)
class StoreRefund:
    store: str
    amount_krw: int
    eligible: bool
    rate: float
    refund_krw: int
    instant: bool
    rule: str


@dataclass(frozen=True)
class TaxRefund:
    stores: tuple[StoreRefund, ...]
    refund_krw: int
    note: str


@dataclass(frozen=True)
class Line:
    product_id: str
    qty: int = 1
    store: str = "Olive Young"


def tax_refund(lines: Sequence[Line], catalog: Catalog, rules: Rules) -> TaxRefund:
    tr = rules.tax_refund
    per_store: dict[str, int] = defaultdict(int)
    for ln in lines:
        per_store[ln.store] += catalog[ln.product_id].price_krw * ln.qty
    rows: list[StoreRefund] = []
    total, instant_total = 0, 0
    for store in sorted(per_store):
        amt = per_store[store]
        eligible = amt >= tr.min_per_transaction
        rate = tr.rate_for(amt) if eligible else 0.0
        refund = int(round(amt * rate)) if eligible else 0
        instant = eligible and amt < tr.instant_max_per_transaction and instant_total + amt <= tr.instant_max_total
        if instant:
            instant_total += amt
        total += refund
        rule = (f"R4: ₩{amt:,} ≥ ₩{tr.min_per_transaction:,} → × {rate*100:.1f}% = ₩{refund:,}" if eligible
                else f"R4: ₩{amt:,} < ₩{tr.min_per_transaction:,} → not eligible")
        rows.append(StoreRefund(store, amt, eligible, rate, refund, instant, rule))
    return TaxRefund(tuple(rows), total, tr.note)


# ---------- composite results ----------

@dataclass(frozen=True)
class Profile:
    currency: Currency = "USD"
    skin: str = "combination"
    lang: str = "en"


# ---------- R5: the verdict (court concept — a ruling with written reasons) ----------

VerdictKind = Literal["buy_here", "buy_home", "similar", "unknown"]
VERDICT_MIN_PCT = 10        # below this gap either way, the court calls it "similar"


@dataclass(frozen=True)
class Verdict:
    kind: VerdictKind
    saving_pct: int                 # positive = Korea cheaper
    reasons: tuple[str, ...]        # machine-readable reason codes the UI translates
    rule: str

    @property
    def decisive(self) -> bool:
        return self.kind in ("buy_here", "buy_home")


def judge(price: PriceComparison | None, fit: SkinFit, duplicates: Sequence[Duplicate], shelf_price: bool) -> Verdict:
    """Deterministic ruling: price gap decides, skin fit and duplicates are entered as remarks."""
    reasons: list[str] = []
    if price is None:
        reasons.append("home_price_unknown")
        kind, pct = "unknown", 0
    else:
        pct = price.saving_pct
        if pct >= VERDICT_MIN_PCT:
            kind = "buy_here"
            reasons.append("cheaper_here")
        elif pct <= -VERDICT_MIN_PCT:
            kind = "buy_home"
            reasons.append("cheaper_home")
        else:
            kind = "similar"
            reasons.append("similar_price")
    if shelf_price:
        reasons.append("shelf_price_used")
    if fit.level == "caution":
        reasons.append("skin_caution")
    if any(d.same_product for d in duplicates):
        reasons.append("already_in_list")
    elif duplicates:
        reasons.append("similar_in_list")
    rule = f"R5: gap {pct:+d}% vs ±{VERDICT_MIN_PCT}% threshold → {kind}" if price else "R5: no home price → no ruling"
    return Verdict(kind, pct, tuple(reasons), rule)


@dataclass(frozen=True)
class ScanResult:
    product: Product
    price: PriceComparison | None
    korea_local: float
    fit: SkinFit
    duplicates: tuple[Duplicate, ...]
    evidence: tuple[str, ...]
    verdict: Verdict

    def to_dict(self) -> dict:
        d = asdict(self)
        d["product"] = {**asdict(self.product), "brand": {"en": self.product.brand_en, "ko": self.product.brand_ko},
                        "name": {"en": self.product.name_en, "ko": self.product.name_ko}}
        return d


def scan(product: Product, profile: Profile, basket: Iterable[Product], rules: Rules, shelf_price: bool = False) -> ScanResult:
    """`shelf_price=True` means product.price_krw is the price the user typed from the shelf, not the catalog's."""
    price = compare_price(product, profile.currency, rules)
    korea_local = krw_to(product.price_krw, profile.currency, rules)
    fit = skin_fit(product, profile.skin)
    dups = tuple(find_duplicates(product, basket, rules.duplicate_min_shared_tags))
    verdict = judge(price, fit, dups, shelf_price)
    src = "shelf" if shelf_price else "catalog"
    price_rule = price.rule if price else f"R1: ₩{product.price_krw:,} ÷ {rules.fx_krw_per_unit[profile.currency]:g} = {money(korea_local, profile.currency)} (home price unknown)"
    evidence = (f"{price_rule} [{src} price, fx as of {rules.as_of}]", fit.rule,
                *(f"R3: shares {', '.join(d.shared_tags)} with {d.product_id}" for d in dups), verdict.rule)
    return ScanResult(product, price, korea_local, fit, dups, evidence, verdict)


@dataclass(frozen=True)
class SummaryLine:
    product_id: str
    qty: int
    store: str
    price_krw: int
    line_krw: int
    home_local: float | None
    rebuy_url: str


@dataclass(frozen=True)
class TripSummary:
    currency: Currency
    lines: tuple[SummaryLine, ...]
    total_krw: int
    korea_local: float
    home_local: float
    refund: TaxRefund
    refund_local: float
    net_local: float
    saved_local: float
    saved_pct: int
    home_known_lines: int
    evidence: tuple[str, ...]
    fx: float
    as_of: str
    totals: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def summarize(lines: Sequence[Line], catalog: Catalog, profile: Profile, rules: Rules) -> TripSummary:
    cur = profile.currency
    out_lines: list[SummaryLine] = []
    total_krw, home_total, known_krw, known_lines = 0, 0.0, 0, 0
    for ln in lines:
        p = catalog[ln.product_id]
        line_krw = p.price_krw * ln.qty
        total_krw += line_krw
        home_line = p.home_price[cur] * ln.qty if cur in p.home_price else None
        if home_line is not None:
            home_total += home_line
            known_krw += line_krw
            known_lines += 1
        out_lines.append(SummaryLine(p.id, ln.qty, ln.store, p.price_krw, line_krw, home_line, p.rebuy_url))
    korea_local = krw_to(total_krw, cur, rules)
    refund = tax_refund(lines, catalog, rules)
    refund_local = krw_to(refund.refund_krw, cur, rules)
    net_local = round_money(korea_local - refund_local, cur)
    # Savings are only claimed for lines whose home price we actually know; the refund is
    # apportioned to those lines by their share of the Korea total.
    known_net = round_money(krw_to(known_krw, cur, rules) - refund_local * (known_krw / total_krw if total_krw else 0), cur)
    saved_local = round_money(home_total - known_net, cur) if known_lines else 0.0
    fx = rules.fx_krw_per_unit[cur]
    evidence = (
        f"Σ Korea ₩{total_krw:,} ÷ {fx:g} = {money(korea_local, cur)}",
        f"Σ home (for {known_lines}/{len(lines)} items with a known home price) {money(home_total, cur)}",
        *(s.rule for s in refund.stores),
        f"net = {money(korea_local, cur)} − refund {money(refund_local, cur)} = {money(net_local, cur)}",
        f"saved vs home = {money(home_total, cur)} − {money(known_net, cur)} = {money(saved_local, cur)}",
    )
    return TripSummary(
        currency=cur, lines=tuple(out_lines), total_krw=total_krw, korea_local=korea_local,
        home_local=round_money(home_total, cur), refund=refund, refund_local=refund_local,
        net_local=net_local, saved_local=saved_local,
        saved_pct=round(saved_local / home_total * 100) if home_total else 0,
        home_known_lines=known_lines, evidence=evidence, fx=fx, as_of=rules.as_of,
    )
