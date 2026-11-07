"""
Reviewer console for product requests (runs on the operator's machine, no web admin needed).

    python manage.py requests                 # pending requests
    python manage.py requests --all           # every request with status
    python manage.py approve <id> <product-id> [--note "..."]
    python manage.py reject  <id> [--note "..."]
    python manage.py skeleton <id>            # JSON skeleton to paste into kbeauty/products.json

Approving links the request to a catalog product id, so add the product to products.json first
(the id must exist there), then approve; the user sees the product in the app on their next visit.
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from kbeauty.catalog import Catalog
from kbeauty.config import get_settings
from kbeauty.store import Store

STATUS_MARK = {"pending": "…", "approved": "✓", "rejected": "✗"}


def _fmt(ts: float | None) -> str:
    return time.strftime("%m-%d %H:%M", time.localtime(ts)) if ts else ""


def cmd_requests(store: Store, show_all: bool) -> None:
    rows = store.all_requests(None if show_all else "pending")
    if not rows:
        print("no requests")
        return
    for r in rows:
        print(f"{STATUS_MARK[r.status]} {r.id}  {_fmt(r.created_at)}  [{r.brand or '-'}] {r.name}"
              + (f"  — {r.note}" if r.note else "")
              + (f"  → {r.product_id} ({r.admin_note})" if r.status != "pending" else ""))


def cmd_review(store: Store, catalog: Catalog, rid: str, status: str, product_id: str | None, note: str) -> None:
    if status == "approved" and product_id not in catalog:
        sys.exit(f"'{product_id}' is not in products.json — add it first, then approve.")
    r = store.review_request(rid, status, note, product_id)
    if r is None:
        sys.exit(f"no request with id {rid}")
    print(f"{STATUS_MARK[r.status]} {r.id} {r.status}" + (f" → {r.product_id}" if r.product_id else ""))


def cmd_skeleton(store: Store, rid: str) -> None:
    r = next((x for x in store.all_requests() if x.id == rid), None)
    if r is None:
        sys.exit(f"no request with id {rid}")
    slug = "-".join(w for w in f"{r.brand} {r.name}".lower().replace("&", "and").split() if w.isalnum())[:60] or "new-product"
    print(json.dumps({
        "id": slug, "brand_en": r.brand, "brand_ko": r.brand, "name_en": r.name, "name_ko": r.name,
        "category": "serum", "tags": [], "size": "", "price_krw": 0, "home_price": {}, "rebuy_url": "", "image": "",
    }, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("requests").add_argument("--all", action="store_true")
    approve = sub.add_parser("approve")
    approve.add_argument("id")
    approve.add_argument("product_id")
    approve.add_argument("--note", default="")
    reject = sub.add_parser("reject")
    reject.add_argument("id")
    reject.add_argument("--note", default="")
    sub.add_parser("skeleton").add_argument("id")
    a = ap.parse_args(argv)

    settings = get_settings()
    store = Store(settings.db_path)
    if a.cmd == "requests":
        cmd_requests(store, a.all)
    elif a.cmd == "approve":
        cmd_review(store, Catalog.load(settings.products_path), a.id, "approved", a.product_id, a.note)
    elif a.cmd == "reject":
        cmd_review(store, None, a.id, "rejected", None, a.note)
    elif a.cmd == "skeleton":
        cmd_skeleton(store, a.id)


if __name__ == "__main__":
    main()
