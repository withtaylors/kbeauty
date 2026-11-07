"""Product catalog and pricing rules — typed, validated, loaded once."""
from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

Currency = str  # "USD" | "JPY" | "CNY"


@dataclass(frozen=True)
class Product:
    id: str
    brand_en: str
    brand_ko: str
    name_en: str
    name_ko: str
    category: str
    tags: tuple[str, ...]
    size: str
    price_krw: int
    home_price: Mapping[Currency, float]
    rebuy_url: str = ""
    image: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> Product:
        if d["price_krw"] <= 0:
            raise ValueError(f"{d['id']}: price_krw must be positive")
        return cls(
            id=d["id"], brand_en=d["brand"]["en"], brand_ko=d["brand"]["ko"],
            name_en=d["name"]["en"], name_ko=d["name"]["ko"], category=d["category"],
            tags=tuple(d["tags"]), size=d["size"], price_krw=int(d["price_krw"]),
            home_price={k: float(v) for k, v in d["home_price"].items()},
            rebuy_url=d.get("rebuy_url", ""), image=d.get("image", ""),
        )

    def brief(self) -> dict:
        return {"id": self.id, "brand": self.brand_en, "name": self.name_en, "name_ko": self.name_ko,
                "price_krw": self.price_krw, "image": self.image, "category": self.category}


@dataclass(frozen=True)
class RefundBand:
    lower: int
    upper: int | None
    rate: float


@dataclass(frozen=True)
class TaxRefundRules:
    min_per_transaction: int
    instant_max_per_transaction: int
    instant_max_total: int
    bands: tuple[RefundBand, ...]
    note: str

    def rate_for(self, amount: int) -> float:
        for b in self.bands:
            if amount >= b.lower and (b.upper is None or amount < b.upper):
                return b.rate
        return 0.0


@dataclass(frozen=True)
class Rules:
    as_of: str
    fx_krw_per_unit: Mapping[Currency, float]
    tax_refund: TaxRefundRules
    duplicate_min_shared_tags: int

    @classmethod
    def from_dict(cls, d: dict) -> Rules:
        tr = d["tax_refund"]
        return cls(
            as_of=d["as_of"],
            fx_krw_per_unit={k: float(v) for k, v in d["fx"].items() if k != "note"},
            tax_refund=TaxRefundRules(
                min_per_transaction=int(tr["min_per_transaction"]),
                instant_max_per_transaction=int(tr["instant_max_per_transaction"]),
                instant_max_total=int(tr["instant_max_total"]),
                bands=tuple(RefundBand(int(b["from"]), (int(b["to"]) if b["to"] is not None else None), float(b["rate"]))
                            for b in tr["bands"]),
                note=tr["note"],
            ),
            duplicate_min_shared_tags=int(d["duplicate"]["min_shared_tags"]),
        )


class Catalog:
    """Read-only product lookup."""

    def __init__(self, products: Mapping[str, Product]):
        self._products = dict(products)

    @classmethod
    def load(cls, path: Path) -> Catalog:
        data = json.loads(path.read_text(encoding="utf-8"))
        products = [Product.from_dict(p) for p in data["products"]]
        ids = [p.id for p in products]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate product ids in catalog")
        return cls({p.id: p for p in products})

    def __len__(self) -> int:
        return len(self._products)

    def __contains__(self, pid: object) -> bool:
        return pid in self._products

    def __iter__(self) -> Iterator[Product]:
        return iter(self._products.values())

    def get(self, pid: str) -> Product | None:
        return self._products.get(pid)

    def __getitem__(self, pid: str) -> Product:
        return self._products[pid]


def load_rules(path: Path) -> Rules:
    return Rules.from_dict(json.loads(path.read_text(encoding="utf-8")))
