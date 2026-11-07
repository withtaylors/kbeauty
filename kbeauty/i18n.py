"""Translation tables for product cards.  Descriptions are generated from these tables, not by an LLM."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .catalog import Product

LANGS = ("en", "ko")

CATEGORY = {
    "toner":     {"en": "Toner", "ja": "化粧水・トナー", "zh": "爽肤水", "ko": "토너"},
    "serum":     {"en": "Serum / Essence", "ja": "美容液", "zh": "精华", "ko": "세럼·에센스"},
    "cream":     {"en": "Moisturizer", "ja": "クリーム", "zh": "面霜", "ko": "크림"},
    "sunscreen": {"en": "Sunscreen", "ja": "日焼け止め", "zh": "防晒", "ko": "선크림"},
    "cleanser":  {"en": "Cleanser", "ja": "クレンジング", "zh": "洁面", "ko": "클렌저"},
    "mask":      {"en": "Mask", "ja": "マスク・パック", "zh": "面膜", "ko": "마스크"},
    "pad":       {"en": "Toner Pad", "ja": "トナーパッド", "zh": "化妆棉片", "ko": "패드"},
    "lip":       {"en": "Lip", "ja": "リップ", "zh": "唇部", "ko": "립"},
    "cushion":   {"en": "Cushion Foundation", "ja": "クッションファンデ", "zh": "气垫", "ko": "쿠션"},
    "base":      {"en": "Color-correcting Base", "ja": "下地", "zh": "妆前乳", "ko": "베이스"},
    "blush":     {"en": "Blush", "ja": "チーク", "zh": "腮红", "ko": "블러셔"},
}

TAG = {
    "sea_minerals":     {"en": "sea-water minerals", "ja": "海洋深層水ミネラル", "zh": "海洋矿物质", "ko": "해양 미네랄"},
    "panthenol":        {"en": "panthenol", "ja": "パンテノール", "zh": "泛醇", "ko": "판테놀"},
    "exfoliating":      {"en": "gentle exfoliation", "ja": "やさしい角質ケア", "zh": "温和去角质", "ko": "각질 케어"},
    "heartleaf":        {"en": "heartleaf", "ja": "ドクダミ", "zh": "鱼腥草", "ko": "어성초"},
    "soothing":         {"en": "soothing", "ja": "鎮静", "zh": "舒缓", "ko": "진정"},
    "hyaluronic_acid":  {"en": "hyaluronic acid", "ja": "ヒアルロン酸", "zh": "玻尿酸", "ko": "히알루론산"},
    "hydrating":        {"en": "deep hydration", "ja": "保湿", "zh": "补水", "ko": "보습"},
    "rice":             {"en": "rice extract", "ja": "米エキス", "zh": "大米提取物", "ko": "쌀 추출물"},
    "probiotics":       {"en": "probiotics", "ja": "プロバイオティクス", "zh": "益生菌", "ko": "프로바이오틱스"},
    "spf50":            {"en": "SPF50+ PA++++", "ja": "SPF50+ PA++++", "zh": "SPF50+ PA++++", "ko": "SPF50+"},
    "propolis":         {"en": "propolis", "ja": "プロポリス", "zh": "蜂胶", "ko": "프로폴리스"},
    "niacinamide":      {"en": "niacinamide", "ja": "ナイアシンアミド", "zh": "烟酰胺", "ko": "나이아신아마이드"},
    "brightening":      {"en": "brightening", "ja": "透明感ケア", "zh": "提亮", "ko": "미백·광채"},
    "snail_mucin":      {"en": "snail mucin", "ja": "カタツムリ粘液", "zh": "蜗牛黏液", "ko": "달팽이 뮤신"},
    "repair":           {"en": "skin repair", "ja": "肌修復", "zh": "修护", "ko": "재생"},
    "bha":              {"en": "BHA", "ja": "BHA", "zh": "水杨酸(BHA)", "ko": "BHA"},
    "tea_tree":         {"en": "tea tree", "ja": "ティーツリー", "zh": "茶树", "ko": "티트리"},
    "low_ph":           {"en": "low pH", "ja": "弱酸性", "zh": "弱酸性", "ko": "약산성"},
    "overnight":        {"en": "overnight care", "ja": "夜用ケア", "zh": "夜间护理", "ko": "나이트 케어"},
    "berry":            {"en": "berry extract", "ja": "ベリーエキス", "zh": "浆果提取物", "ko": "베리"},
    "vitamin_c":        {"en": "vitamin C", "ja": "ビタミンC", "zh": "维生素C", "ko": "비타민C"},
    "pore_care":        {"en": "pore care", "ja": "毛穴ケア", "zh": "毛孔护理", "ko": "모공 케어"},
    "pdrn":             {"en": "PDRN", "ja": "PDRN", "zh": "PDRN", "ko": "PDRN"},
    "peptide":          {"en": "peptides", "ja": "ペプチド", "zh": "多肽", "ko": "펩타이드"},
    "centella":         {"en": "centella (cica)", "ja": "ツボクサ(シカ)", "zh": "积雪草(CICA)", "ko": "병풀(시카)"},
    "glossy":           {"en": "glossy finish", "ja": "ツヤ仕上げ", "zh": "水光感", "ko": "글로시"},
    "long_lasting":     {"en": "long-lasting", "ja": "崩れにくい", "zh": "持久", "ko": "지속력"},
    "tint":             {"en": "tint", "ja": "ティント", "zh": "染唇液", "ko": "틴트"},
    "full_coverage":    {"en": "full coverage", "ja": "高カバー", "zh": "高遮瑕", "ko": "고커버"},
    "matte":            {"en": "matte finish", "ja": "マット仕上げ", "zh": "哑光", "ko": "매트"},
    "oil_control":      {"en": "oil control", "ja": "皮脂ケア", "zh": "控油", "ko": "피지 케어"},
    "ceramide":         {"en": "ceramides", "ja": "セラミド", "zh": "神经酰胺", "ko": "세라마이드"},
    "barrier":          {"en": "barrier care", "ja": "バリアケア", "zh": "屏障修护", "ko": "장벽 케어"},
    "fragrance_free":   {"en": "fragrance-free", "ja": "無香料", "zh": "无香料", "ko": "무향"},
    "galactomyces":     {"en": "galactomyces ferment", "ja": "ガラクトミセス", "zh": "半乳糖酵母", "ko": "갈락토미세스"},
    "glutathione":      {"en": "glutathione", "ja": "グルタチオン", "zh": "谷胱甘肽", "ko": "글루타치온"},
    "oil_cleanse":      {"en": "oil cleansing", "ja": "オイルクレンジング", "zh": "油状卸妆", "ko": "오일 클렌징"},
    "makeup_remover":   {"en": "makeup remover", "ja": "メイク落とし", "zh": "卸妆", "ko": "메이크업 리무버"},
    "green_tea":        {"en": "green tea", "ja": "緑茶", "zh": "绿茶", "ko": "녹차"},
    "birch_sap":        {"en": "birch sap", "ja": "白樺樹液", "zh": "桦树汁", "ko": "자작나무 수액"},
    "cica":             {"en": "cica", "ja": "シカ", "zh": "CICA", "ko": "시카"},
    "microneedle":      {"en": "micro-spicules", "ja": "マイクロニードル", "zh": "微针", "ko": "미세침"},
    "collagen":         {"en": "collagen", "ja": "コラーゲン", "zh": "胶原蛋白", "ko": "콜라겐"},
    "white_truffle":    {"en": "white truffle", "ja": "白トリュフ", "zh": "白松露", "ko": "화이트 트러플"},
    "glow":             {"en": "dewy glow", "ja": "ツヤ肌", "zh": "光泽", "ko": "광채"},
    "soybean":          {"en": "fermented soybean", "ja": "大豆発酵", "zh": "发酵大豆", "ko": "발효 콩"},
    "dark_spot":        {"en": "dark-spot care", "ja": "シミケア", "zh": "淡斑", "ko": "잡티 케어"},
    "color_correcting": {"en": "redness color-correcting", "ja": "赤み補正", "zh": "修正泛红", "ko": "붉은기 보정"},
    "blurry":           {"en": "soft-blur finish", "ja": "ぼかし仕上げ", "zh": "柔雾", "ko": "블러"},
    "lip_cheek":        {"en": "lip & cheek", "ja": "リップ&チーク", "zh": "唇颊两用", "ko": "립앤치크"},
    "lip_balm":         {"en": "melting balm", "ja": "リップバーム", "zh": "润唇膏", "ko": "멜팅 밤"},
    "liquid_blush":     {"en": "liquid blush", "ja": "リキッドチーク", "zh": "液体腮红", "ko": "리퀴드 블러셔"},
}

SKIN = {
    "dry":         {"en": "dry", "ja": "乾燥肌", "zh": "干性", "ko": "건성"},
    "oily":        {"en": "oily", "ja": "脂性肌", "zh": "油性", "ko": "지성"},
    "combination": {"en": "combination", "ja": "混合肌", "zh": "混合性", "ko": "복합성"},
    "sensitive":   {"en": "sensitive", "ja": "敏感肌", "zh": "敏感", "ko": "민감성"},
}

FIT_LABEL = {
    "good":    {"en": "Great for your skin", "ja": "あなたの肌にぴったり", "zh": "非常适合你的肤质", "ko": "내 피부에 잘 맞음"},
    "ok":      {"en": "Fine for your skin", "ja": "問題なく使えます", "zh": "可以使用", "ko": "무난함"},
    "caution": {"en": "Patch test first", "ja": "まずパッチテストを", "zh": "建议先局部试用", "ko": "주의 필요"},
}


def t(table: dict, key: str, lang: str) -> str:
    row = table.get(key) or {}
    return row.get(lang) or row.get("en") or key


def describe(product: Product, lang: str) -> str:
    """Rule-based one-line description.  Facts come straight from the catalog; only the wording changes.
    Works without a brand or tags (typed-in products) instead of producing broken sentences."""
    cat = t(CATEGORY, product.category, lang)
    tags = [t(TAG, x, lang) for x in product.tags]
    if lang == "ko":
        sz = f"({product.size})" if product.size else ""
        head = f"{product.brand_ko}의 {cat}{sz}" if product.brand_ko else f"{cat}{sz}"
        return f"{head}. 주요 특징은 {', '.join(tags)}입니다." if tags else f"{head}입니다."
    if lang == "ja":
        sz = f"（{product.size}）" if product.size else ""
        head = f"{product.brand_en}の{cat}{sz}" if product.brand_en else f"{cat}{sz}"
        return f"{head}。主な特徴は{'・'.join(tags)}です。" if tags else f"{head}です。"
    if lang == "zh":
        sz = f"（{product.size}）" if product.size else ""
        head = f"{product.brand_en}的{cat}{sz}" if product.brand_en else f"{cat}{sz}"
        return f"{head}。主要特点：{'、'.join(tags)}。" if tags else f"{head}。"
    sz = f" ({product.size})" if product.size else ""
    head = f"A {cat.lower()} from {product.brand_en}{sz}" if product.brand_en else f"A {cat.lower()}{sz}"
    return f"{head}. Key points: {', '.join(tags)}." if tags else f"{head}."
