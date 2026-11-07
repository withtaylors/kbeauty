"""
K-Beauty Scan — HTTP API.

    uvicorn app:app --reload --port 8000     →  http://localhost:8000

Layers:  app.py (HTTP)  →  services (this file, thin)  →  kbeauty.engine / vision / store (domain)
"""
from __future__ import annotations

import hashlib
import logging
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from kbeauty import engine
from kbeauty.catalog import Catalog, Product, load_rules
from kbeauty.config import Settings, get_settings
from kbeauty.fx import FrankfurterClient, LiveFx
from kbeauty.i18n import CATEGORY, FIT_LABEL, SKIN, TAG, describe, t
from kbeauty.sources import LiveProduct, LiveSearch, NaverShoppingClient
from kbeauty.store import Store
from kbeauty.vision import InvalidImage, TextSearch, build_vision, decode_image
from kbeauty.webprice import TavilyClient, WebPrice, WebPriceFinder

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("kbeauty.app")


# ---------- app state ----------

class AppState:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.catalog = Catalog.load(settings.products_path)
        self.base_rules = load_rules(settings.rules_path)
        self.fx = LiveFx(FrankfurterClient() if settings.live_fx else None, settings.supported_currencies)
        self.store = Store(settings.db_path)
        self.search = TextSearch(self.catalog)
        self.vision = build_vision(settings, self.catalog)
        client = (NaverShoppingClient(settings.naver_client_id, settings.naver_client_secret)
                  if settings.live_search_enabled else None)
        self.live = LiveSearch(client)
        self.webprice = WebPriceFinder(TavilyClient(settings.tavily_api_key) if settings.tavily_api_key else None)
        log.info("catalog=%d, rules as of %s, vision=%s, live=%s", len(self.catalog), self.rules.as_of,
                 self.vision.enabled, self.live.enabled)

    @property
    def rules(self):
        """Rules with the latest exchange rates applied (file values until the first successful fetch)."""
        return self.fx.apply(self.base_rules)

    async def fresh_rules(self):
        if self.fx.stale:
            await self.fx.refresh()
        return self.rules

    async def with_home_price(self, product: Product, currency: str) -> tuple[Product, WebPrice | None]:
        """Fill a missing home price from the web (sourced, cached).  Catalog prices are never overridden."""
        if currency in product.home_price or not self.webprice.enabled:
            return product, None
        korea_local = engine.krw_to(product.price_krw, currency, self.rules)
        wp = await self.webprice.lookup(product.brand_en, product.name_en, currency, korea_local)
        if wp is None:
            return product, None
        return replace(product, home_price={**product.home_price, currency: wp.price}), wp

    # A product id can point at the curated catalog, a live listing ("live:<id>") or a typed-in product ("web:<hash>").
    def resolve(self, pid: str, snapshot: dict | None = None) -> Product | None:
        """Product for a catalog or live id.  A catalog item's snapshot may carry the shelf price the user typed."""
        if pid in self.catalog:
            p = self.catalog[pid]
            shelf = (snapshot or {}).get("shelf_price_krw")
            return replace(p, price_krw=int(shelf)) if shelf else p
        if pid.startswith(("live:", "web:")):
            lp = self.live.get(pid)
            if lp is None and snapshot:
                lp = LiveProduct(**snapshot)
                self.live.remember(lp)
            return lp.to_product() if lp else None
        return None

    def brief(self, pid: str, snapshot: dict | None = None) -> dict:
        if pid in self.catalog:
            p = self.resolve(pid, snapshot)
            return {**p.brief(), "source": "catalog", "shelf_price": bool((snapshot or {}).get("shelf_price_krw"))}
        lp = self.live.get(pid) or (LiveProduct(**snapshot) if snapshot else None)
        return lp.brief() if lp else {"id": pid, "name": pid, "brand": "", "price_krw": 0, "image": "", "category": "unknown", "source": "unknown"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.ctx = AppState(get_settings())
    await app.state.ctx.fx.refresh()
    yield


app = FastAPI(title="K-Beauty Scan", version="0.2.0", lifespan=lifespan)


def ctx(request: Request) -> AppState:
    return request.app.state.ctx


def current_user(request: Request, x_user_id: Annotated[str | None, Header()] = None) -> str:
    """Anonymous device-scoped identity.  Replace with session/JWT validation when login lands."""
    return ctx(request).store.ensure_user(x_user_id)


Ctx = Annotated[AppState, Depends(ctx)]
User = Annotated[str, Depends(current_user)]


@app.exception_handler(InvalidImage)
async def invalid_image(_: Request, exc: InvalidImage):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


# ---------- request / response models ----------

Lang = Literal["en", "ko"]
CurrencyCode = Literal["USD", "JPY"]
Skin = Literal["dry", "oily", "combination", "sensitive"]


class ProfileIn(BaseModel):
    lang: Lang
    currency: CurrencyCode
    skin: Skin


class ScanIn(BaseModel):
    """Exactly one of image_b64 / query / product_id."""
    image_b64: str | None = Field(default=None, description="data:image/...;base64,... or raw base64")
    query: str | None = Field(default=None, max_length=120)
    product_id: str | None = Field(default=None, max_length=80)
    shelf_price_krw: int | None = Field(default=None, ge=100, le=10_000_000, description="price seen on the shelf, in KRW")

    @model_validator(mode="after")
    def exactly_one(self):
        if sum(x is not None for x in (self.image_b64, self.query, self.product_id)) != 1:
            raise ValueError("provide exactly one of image_b64, query, product_id")
        return self


class AddIn(BaseModel):
    product_id: str = Field(max_length=80)
    store: str = Field(default="Olive Young", max_length=40)
    shelf_price_krw: int | None = Field(default=None, ge=100, le=10_000_000, description="price the user saw on the shelf")


class QtyIn(BaseModel):
    qty: int = Field(ge=0, le=99)


class JudgeIn(BaseModel):
    """A product that isn't in the DB: the user types its name and the shelf price."""
    name: str = Field(min_length=2, max_length=120)
    shelf_price_krw: int = Field(ge=100, le=10_000_000)


class RequestIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    brand: str = Field(default="", max_length=60)
    note: str = Field(default="", max_length=500)


# ---------- presentation helpers ----------

def _profile(c: AppState, uid: str) -> engine.Profile:
    p = c.store.get_profile(uid)
    return engine.Profile(currency=p.currency, skin=p.skin, lang=p.lang)


def _basket(c: AppState, uid: str) -> list[Product]:
    out = []
    for i in c.store.list_items(uid):
        p = c.resolve(i.product_id, i.snapshot)
        if p:
            out.append(p)
    return out


def _card(c: AppState, uid: str, product: Product, shelf_price_krw: int | None = None, web: WebPrice | None = None) -> dict:
    prof = _profile(c, uid)
    shelf = shelf_price_krw is not None
    if shelf:
        product = replace(product, price_krw=shelf_price_krw)
    res = engine.scan(product, prof, _basket(c, uid), c.rules, shelf_price=shelf)
    lang, cur = prof.lang, prof.currency
    out = res.to_dict()
    out["verdict"] = {"kind": res.verdict.kind, "saving_pct": res.verdict.saving_pct, "reasons": list(res.verdict.reasons),
                      "decisive": res.verdict.decisive}
    out["fx"] = {"rate": c.rules.fx_krw_per_unit[cur], "as_of": c.rules.as_of,
                 "source": c.fx.snapshot.source if c.fx.snapshot else "rules.json"}
    live = c.live.get(product.id) if product.id.startswith(("live:", "web:")) else None
    out["source"] = ("manual" if product.id.startswith("web:") else "live") if live else "catalog"
    out["home_source"] = web.to_dict() if web else ({"kind": "catalog"} if res.price else None)
    out["display"] = {
        "name": product.name_en, "name_ko": product.name_ko, "brand": product.brand_en,
        "image": product.image, "mall": live.mall if live else "", "link": live.link if live else "",
        "category": t(CATEGORY, product.category, lang),
        "tags": [t(TAG, x, lang) for x in product.tags],
        "description": describe(product, lang),
        "fit_label": t(FIT_LABEL, res.fit.level, lang),
        "fit_good": [t(TAG, x, lang) for x in res.fit.good],
        "fit_caution": [t(TAG, x, lang) for x in res.fit.caution],
        "skin": t(SKIN, prof.skin, lang),
        "korea": engine.money(res.korea_local, cur),
        "shelf_price": shelf,
        "home": engine.money(res.price.home_local, cur) if res.price else None,
        "saving": engine.money(abs(res.price.saving_local), cur) if res.price else None,
        "duplicates": [{"id": d.product_id, "name": (c.resolve(d.product_id) or product).name_en, "same": d.same_product,
                        "shared": [t(TAG, x, lang) for x in d.shared_tags]} for d in res.duplicates],
    }
    return out


def _request_view(c: AppState, r) -> dict:
    out = {"id": r.id, "name": r.name, "brand": r.brand, "note": r.note, "status": r.status, "admin_note": r.admin_note,
           "created_at": r.created_at, "reviewed_at": r.reviewed_at, "product": None}
    if r.status == "approved" and r.product_id and r.product_id in c.catalog:
        out["product"] = c.catalog[r.product_id].brief()
    return out


def _list_view(c: AppState, uid: str) -> dict:
    prof = _profile(c, uid)
    items = c.store.list_items(uid)
    rows, total = [], 0
    for it in items:
        p = c.resolve(it.product_id, it.snapshot)
        if p is None:
            continue
        total += p.price_krw * it.qty
        rows.append({**c.brief(p.id, it.snapshot), "id": it.id, "product_id": p.id, "qty": it.qty, "store": it.store,
                     "korea": engine.money(engine.krw_to(p.price_krw * it.qty, prof.currency, c.rules), prof.currency)})
    return {"items": rows, "total_krw": total, "total_local": engine.money(engine.krw_to(total, prof.currency, c.rules), prof.currency)}


# ---------- routes ----------

@app.get("/api/health")
def health(c: Ctx):
    return {"ok": True, "vision": c.vision.enabled, "live_search": c.live.enabled, "products": len(c.catalog),
            "rules_as_of": c.rules.as_of, "fx_source": c.fx.snapshot.source if c.fx.snapshot else "rules.json"}


@app.get("/api/me")
def me(c: Ctx, uid: User):
    p = c.store.get_profile(uid)
    return {"user_id": uid, "profile": p.__dict__, "list": _list_view(c, uid), "vision": c.vision.enabled, "live_search": c.live.enabled,
            "web_price": c.webprice.enabled}


@app.put("/api/profile")
def put_profile(body: ProfileIn, c: Ctx, uid: User):
    return c.store.save_profile(uid, body.lang, body.currency, body.skin).__dict__


@app.get("/api/products")
def products(c: Ctx, q: str = ""):
    ids = [h.product_id for h in c.search.search(q, limit=8)] if q else [p.id for p in c.catalog]
    return [{**c.catalog[i].brief(), "source": "catalog"} for i in ids]


@app.get("/api/search")
async def unified_search(c: Ctx, q: str = "", limit: int = 10):
    """Text search across the curated catalog and live Olive Young listings (when configured)."""
    q = q.strip()
    if not q:
        raise HTTPException(400, "q is required")
    curated = [{**c.catalog[h.product_id].brief(), "source": "catalog", "score": h.score} for h in c.search.search(q, limit=5, min_score=0.45)]
    live = [p.brief() for p in await c.live.search(q, c.settings.live_olive_young_only, limit=limit)]
    curated_names = {x["name"].lower() for x in curated}
    live = [x for x in live if x["name"].lower() not in curated_names]
    return {"query": q, "results": curated + live, "live_enabled": c.live.enabled,
            "olive_young_only": c.settings.live_olive_young_only}


@app.post("/api/scan")
async def scan(body: ScanIn, c: Ctx, uid: User):
    """Identify a product (photo → vision, text → search, or an explicit pick) and return its card + verdict."""
    await c.fresh_rules()
    if body.product_id is not None:
        product = c.resolve(body.product_id)
        if product is None:
            raise HTTPException(404, "unknown product (live results expire after an hour — search again)")
        c.store.log_scan(uid, "pick", product.id, 1.0, ())
        return {"status": "ok", "method": "pick", "card": await _priced_card(c, uid, product, body.shelf_price_krw)}

    if body.image_b64 is not None:
        payload, mime = decode_image(body.image_b64, c.settings.max_image_bytes)
        ident = await c.vision.identify(payload, mime)
    else:
        ident = c.search.identify(body.query or "")

    c.store.log_scan(uid, ident.method, ident.product_id, ident.confidence, ident.candidates)

    if ident.product_id and (ident.method != "vision" or ident.confidence >= c.settings.confidence_threshold):
        return {"status": "ok", "method": ident.method, "confidence": ident.confidence,
                "card": await _priced_card(c, uid, c.catalog[ident.product_id], body.shelf_price_krw)}
    candidates = [{**c.catalog[i].brief(), "source": "catalog"} for i in ident.candidates]
    # Photo not matched confidently → use the text the model read on the package as a live query.
    if body.image_b64 is not None and ident.seen_text and c.live.enabled:
        candidates += [p.brief() for p in await c.live.search(ident.seen_text, c.settings.live_olive_young_only, limit=6)]
    if candidates:
        return {"status": "choose", "method": ident.method, "confidence": ident.confidence,
                "candidates": candidates, "seen_text": ident.seen_text}
    return {"status": "fallback", "method": ident.method, "error": ident.error,
            "message": "Could not identify the product. Try typing the brand or product name."}


async def _priced_card(c: AppState, uid: str, product: Product, shelf_price_krw: int | None = None) -> dict:
    """Card for a product; a missing home price is looked up on the web first (cached, sourced)."""
    cur = _profile(c, uid).currency
    if shelf_price_krw is not None:
        product = replace(product, price_krw=shelf_price_krw)
    product, web = await c.with_home_price(product, cur)
    return _card(c, uid, product, shelf_price_krw, web)


@app.post("/api/judge")
async def judge(body: JudgeIn, c: Ctx, uid: User):
    """Not in the DB?  Name + shelf price → web home price → the same rules → a ruling."""
    await c.fresh_rules()
    name = " ".join(body.name.split())
    pid = "web:" + hashlib.sha1(name.lower().encode()).hexdigest()[:12]
    lp = LiveProduct(id=pid, title=name, brand="", maker="", price_krw=body.shelf_price_krw,
                     image="", link="", mall="", category_path="")
    c.live.remember(lp)
    c.store.log_scan(uid, "manual", pid, 1.0, ())
    return {"status": "ok", "method": "manual", "web_price_enabled": c.webprice.enabled,
            "card": await _priced_card(c, uid, lp.to_product(), body.shelf_price_krw)}


@app.get("/api/list")
def get_list(c: Ctx, uid: User):
    return _list_view(c, uid)


@app.post("/api/list")
def add_to_list(body: AddIn, c: Ctx, uid: User):
    """Add to the list.  The shelf price the user typed travels with the item, so the trip summary uses it too."""
    snapshot = None
    if body.product_id in c.catalog:
        snapshot = {"shelf_price_krw": body.shelf_price_krw} if body.shelf_price_krw else None
    else:
        lp = c.live.get(body.product_id)
        if lp is None:
            raise HTTPException(404, "unknown product")
        snapshot = {**lp.__dict__, "price_krw": body.shelf_price_krw or lp.price_krw}
    c.store.add_item(uid, body.product_id, body.store, snapshot)
    return _list_view(c, uid)


@app.put("/api/list/{item_id}")
def set_qty(item_id: str, body: QtyIn, c: Ctx, uid: User):
    if not c.store.set_qty(uid, item_id, body.qty):
        raise HTTPException(404, "item not found")
    return _list_view(c, uid)


@app.delete("/api/list")
def clear_list(c: Ctx, uid: User):
    c.store.clear(uid)
    return _list_view(c, uid)


@app.get("/api/requests")
def my_requests(c: Ctx, uid: User):
    """The user's "please add this product" requests and their review status."""
    return {"requests": [_request_view(c, r) for r in c.store.requests_for(uid)]}


@app.post("/api/requests", status_code=201)
def create_request(body: RequestIn, c: Ctx, uid: User):
    r = c.store.add_request(uid, body.name, body.brand, body.note)
    log.info("product request %s: %s %s", r.id, r.brand, r.name)
    return _request_view(c, r)


@app.get("/api/summary")
async def summary(c: Ctx, uid: User):
    items = [(i, c.resolve(i.product_id, i.snapshot)) for i in c.store.list_items(uid)]
    items = [(i, p) for i, p in items if p]
    if not items:
        raise HTTPException(400, "list is empty")
    prof = _profile(c, uid)
    items = [(i, (await c.with_home_price(p, prof.currency))[0]) for i, p in items]
    basket = Catalog({p.id: p for _, p in items})          # engine looks products up by id
    s = engine.summarize([engine.Line(i.product_id, i.qty, i.store) for i, _ in items], basket, prof, c.rules)
    out = s.to_dict()
    cur = prof.currency
    snaps = {i.product_id: i.snapshot for i, _ in items}
    for ln in out["lines"]:
        ln.update(c.brief(ln["product_id"], snaps.get(ln["product_id"])))
    out["display"] = {k: engine.money(getattr(s, k), cur) for k in ("korea_local", "home_local", "refund_local", "net_local", "saved_local")}
    out["display"]["refund_krw"] = f"₩{s.refund.refund_krw:,}"
    out["display"]["total_krw"] = f"₩{s.total_krw:,}"
    return out


# ---------- static ----------

_settings = get_settings()
app.mount("/static", StaticFiles(directory=_settings.static_dir), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(_settings.static_dir / "index.html")
