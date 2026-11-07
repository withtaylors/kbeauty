"""Engine tests.  Every expected number was computed by hand (verification #2: zero error)."""
from kbeauty.engine import Line, Profile, compare_price, find_duplicates, scan, skin_fit, summarize, tax_refund


def test_catalog_integrity(catalog):
    assert len(catalog) == 43
    for p in catalog:
        assert p.price_krw > 0 and set(p.home_price) == {"USD", "JPY", "CNY"} and p.tags


def test_price_compare_usd_by_hand(catalog, rules):
    # 28,000 ÷ 1,343 = 20.849… → $20.85 ; home $29 → saving $8.15 (28%)
    r = compare_price(catalog["anua-heartleaf-toner"], "USD", rules)
    assert (r.korea_local, r.home_local, r.saving_local, r.saving_pct, r.cheaper_in_korea) == (20.85, 29.0, 8.15, 28, True)


def test_price_compare_jpy_by_hand(catalog, rules):
    # 22,000 ÷ 8.505 = 2,586.7 → ¥2,587 ; home ¥2,700 → ¥113 (4%)
    r = compare_price(catalog["torriden-divein-serum"], "JPY", rules)
    assert (r.korea_local, r.saving_local, r.saving_pct) == (2587, 113, 4)


def test_price_compare_can_be_cheaper_at_home(catalog, rules):
    # Weak yen: 32,000 ÷ 8.505 = ¥3,762 > home ¥3,300 → we report it honestly
    r = compare_price(catalog["innisfree-greentea-serum"], "JPY", rules)
    assert not r.cheaper_in_korea and r.saving_local == -462


def test_skin_fit_rules(catalog):
    assert skin_fit(catalog["aestura-atobarrier-cream"], "dry").level == "good"
    s = skin_fit(catalog["medicube-zero-pore-pad"], "sensitive")
    assert s.level == "caution" and set(s.caution) == {"bha", "exfoliating"}
    assert skin_fit(catalog["romand-juicy-tint"], "oily").level == "ok"        # makeup is neutral
    assert skin_fit(catalog["amuse-dew-serum-blush"], "dry").level == "ok"


def test_duplicate_requires_same_category_and_two_shared_tags(catalog):
    basket = [catalog["torriden-divein-serum"], catalog["anua-heartleaf-toner"]]
    d = find_duplicates(catalog["innisfree-greentea-serum"], basket)
    assert len(d) == 1 and d[0].product_id == "torriden-divein-serum"
    assert set(d[0].shared_tags) == {"hyaluronic_acid", "hydrating"}
    assert find_duplicates(catalog["aestura-atobarrier-cream"], [catalog["torriden-divein-serum"]]) == []  # different category
    assert find_duplicates(catalog["boj-relief-sun"], [catalog["skin1004-sun-serum"]]) == []               # only spf50 shared
    same = find_duplicates(catalog["boj-relief-sun"], [catalog["boj-relief-sun"]])
    assert same and same[0].same_product


def test_new_products_duplicates(catalog):
    d = find_duplicates(catalog["romand-glasting-melting-balm"], [catalog["romand-glasting-tint"]])
    assert d and set(d[0].shared_tags) == {"glossy", "hydrating"}
    d2 = find_duplicates(catalog["celimax-heartleaf-bha-pad"], [catalog["medicube-zero-pore-pad"]])
    assert d2 and set(d2[0].shared_tags) == {"bha", "exfoliating"}


def test_tax_refund_bands_by_hand(catalog, rules):
    # 28,000 + 22,000 + 18,000 = 68,000 → 50k–150k band 6.5% → ₩4,420, instant eligible
    r = tax_refund([Line("anua-heartleaf-toner"), Line("torriden-divein-serum"), Line("boj-relief-sun")], catalog, rules)
    assert r.refund_krw == 4420 and r.stores[0].instant
    # ₩12,900 at one store → below ₩15,000 → 0
    assert tax_refund([Line("cosrx-gel-cleanser", store="Daiso")], catalog, rules).refund_krw == 0
    # stores are not merged: 12,000 + 12,000 in two stores → both ineligible
    r2 = tax_refund([Line("cosrx-gel-cleanser", store="A"), Line("cosrx-gel-cleanser", store="B")], catalog, rules)
    assert r2.refund_krw == 0 and len(r2.stores) == 2


def test_summary_by_hand(catalog, rules):
    lines = [Line("anua-heartleaf-toner"), Line("torriden-divein-serum"), Line("boj-relief-sun")]
    s = summarize(lines, catalog, Profile(currency="USD"), rules)
    # 68,000 ÷ 1,343 = 50.63 ; home 29+22+18 = 69 ; refund 4,420 ÷ 1,343 = 3.29
    # net 50.63 − 3.29 = 47.34 ; saved 69 − 47.34 = 21.66 (31%)
    assert (s.total_krw, s.korea_local, s.home_local) == (68000, 50.63, 69.0)
    assert (s.refund_local, s.net_local, s.saved_local, s.saved_pct) == (3.29, 47.34, 21.66, 31)
    assert any("R4" in e for e in s.evidence)


def test_quantities_multiply(catalog, rules):
    s = summarize([Line("boj-relief-sun", qty=3)], catalog, Profile(currency="USD"), rules)
    assert s.total_krw == 54000 and s.lines[0].line_krw == 54000


def test_scan_is_deterministic(catalog, rules):
    prof = Profile(currency="JPY", skin="sensitive")
    a = scan(catalog["vt-reedle-shot"], prof, [catalog["skin1004-centella-ampoule"]], rules)
    b = scan(catalog["vt-reedle-shot"], prof, [catalog["skin1004-centella-ampoule"]], rules)
    assert a == b and a.fit.level == "caution"
