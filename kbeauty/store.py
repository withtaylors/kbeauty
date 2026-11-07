"""
SQLite persistence: per-user profile, shopping list and scan log.

Users are anonymous device-scoped ids for now.  The `users` table already has the columns a
login provider will need; switching to real accounts only changes `current_user()` in app.py.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY, created_at REAL NOT NULL,
  email TEXT UNIQUE, provider TEXT, provider_id TEXT);
CREATE TABLE IF NOT EXISTS profiles (
  user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  lang TEXT NOT NULL DEFAULT 'en', currency TEXT NOT NULL DEFAULT 'USD',
  skin TEXT NOT NULL DEFAULT 'combination', configured INTEGER NOT NULL DEFAULT 0,
  updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS list_items (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  product_id TEXT NOT NULL, qty INTEGER NOT NULL DEFAULT 1 CHECK (qty > 0),
  store TEXT NOT NULL DEFAULT 'Olive Young', snapshot TEXT, created_at REAL NOT NULL,
  UNIQUE (user_id, product_id, store));
CREATE INDEX IF NOT EXISTS idx_list_user ON list_items(user_id, created_at);
CREATE TABLE IF NOT EXISTS product_requests (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL, brand TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected')),
  product_id TEXT, admin_note TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL, reviewed_at REAL);
CREATE INDEX IF NOT EXISTS idx_req_status ON product_requests(status, created_at);
CREATE TABLE IF NOT EXISTS scans (
  id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  method TEXT NOT NULL, product_id TEXT, confidence REAL, candidates TEXT NOT NULL,
  created_at REAL NOT NULL);
"""


@dataclass(frozen=True)
class ProfileRecord:
    lang: str
    currency: str
    skin: str
    configured: bool


@dataclass(frozen=True)
class ListItem:
    id: str
    product_id: str
    qty: int
    store: str
    snapshot: dict | None = None    # live products: the listing as it was when added


@dataclass(frozen=True)
class ProductRequest:
    """A user's "this product isn't in your DB" request; reviewed by a person via manage.py."""
    id: str
    user_id: str
    name: str
    brand: str
    note: str
    status: str                     # pending | approved | rejected
    product_id: str | None          # catalog id once approved
    admin_note: str
    created_at: float
    reviewed_at: float | None


def _req(r) -> ProductRequest:
    return ProductRequest(r["id"], r["user_id"], r["name"], r["brand"], r["note"], r["status"], r["product_id"],
                          r["admin_note"], r["created_at"], r["reviewed_at"])


class Store:
    def __init__(self, db_path: Path):
        self._path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self._path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    # ---- users ----

    def ensure_user(self, user_id: str | None) -> str:
        """Return a valid user id, creating an anonymous user when needed."""
        with self._conn() as c:
            if user_id and c.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone():
                return user_id
            uid = user_id if (user_id and len(user_id) <= 64 and user_id.isalnum()) else uuid.uuid4().hex
            now = time.time()
            c.execute("INSERT OR IGNORE INTO users(id, created_at) VALUES(?,?)", (uid, now))
            c.execute("INSERT OR IGNORE INTO profiles(user_id, updated_at) VALUES(?,?)", (uid, now))
            return uid

    def merge_users(self, from_id: str, to_id: str) -> None:
        """For a future login: move an anonymous user's data onto an authenticated account."""
        with self._conn() as c:
            c.execute("UPDATE OR IGNORE list_items SET user_id=? WHERE user_id=?", (to_id, from_id))
            c.execute("UPDATE scans SET user_id=? WHERE user_id=?", (to_id, from_id))

    # ---- profile ----

    def get_profile(self, uid: str) -> ProfileRecord:
        with self._conn() as c:
            r = c.execute("SELECT lang, currency, skin, configured FROM profiles WHERE user_id=?", (uid,)).fetchone()
        return ProfileRecord(r["lang"], r["currency"], r["skin"], bool(r["configured"]))

    def save_profile(self, uid: str, lang: str, currency: str, skin: str) -> ProfileRecord:
        with self._conn() as c:
            c.execute("UPDATE profiles SET lang=?, currency=?, skin=?, configured=1, updated_at=? WHERE user_id=?",
                      (lang, currency, skin, time.time(), uid))
        return self.get_profile(uid)

    # ---- list ----

    def list_items(self, uid: str) -> list[ListItem]:
        with self._conn() as c:
            rows = c.execute("SELECT id, product_id, qty, store, snapshot FROM list_items WHERE user_id=? ORDER BY created_at",
                             (uid,)).fetchall()
        return [ListItem(r["id"], r["product_id"], r["qty"], r["store"], json.loads(r["snapshot"]) if r["snapshot"] else None)
                for r in rows]

    def add_item(self, uid: str, product_id: str, store: str = "Olive Young", snapshot: dict | None = None) -> ListItem:
        with self._conn() as c:
            c.execute(
                "INSERT INTO list_items(id, user_id, product_id, qty, store, snapshot, created_at) VALUES(?,?,?,1,?,?,?) "
                "ON CONFLICT(user_id, product_id, store) DO UPDATE SET qty = qty + 1, snapshot = COALESCE(excluded.snapshot, snapshot)",
                (uuid.uuid4().hex[:10], uid, product_id, store, json.dumps(snapshot, ensure_ascii=False) if snapshot else None, time.time()))
            r = c.execute("SELECT id, product_id, qty, store, snapshot FROM list_items WHERE user_id=? AND product_id=? AND store=?",
                          (uid, product_id, store)).fetchone()
        return ListItem(r["id"], r["product_id"], r["qty"], r["store"], json.loads(r["snapshot"]) if r["snapshot"] else None)

    def set_qty(self, uid: str, item_id: str, qty: int) -> bool:
        with self._conn() as c:
            if qty <= 0:
                cur = c.execute("DELETE FROM list_items WHERE id=? AND user_id=?", (item_id, uid))
            else:
                cur = c.execute("UPDATE list_items SET qty=? WHERE id=? AND user_id=?", (qty, item_id, uid))
            return cur.rowcount > 0

    def clear(self, uid: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM list_items WHERE user_id=?", (uid,))

    # ---- scans ----

    def log_scan(self, uid: str, method: str, product_id: str | None, confidence: float, candidates: tuple[str, ...]) -> None:
        with self._conn() as c:
            c.execute("INSERT INTO scans(id, user_id, method, product_id, confidence, candidates, created_at) VALUES(?,?,?,?,?,?,?)",
                      (uuid.uuid4().hex[:10], uid, method, product_id, confidence, json.dumps(list(candidates)), time.time()))

    # ---- product requests ----
    def add_request(self, uid: str, name: str, brand: str = "", note: str = "") -> ProductRequest:
        rid = uuid.uuid4().hex[:8]
        with self._conn() as c:
            c.execute("INSERT INTO product_requests(id, user_id, name, brand, note, created_at) VALUES(?,?,?,?,?,?)",
                      (rid, uid, name.strip(), brand.strip(), note.strip(), time.time()))
            r = c.execute("SELECT * FROM product_requests WHERE id=?", (rid,)).fetchone()
        return _req(r)

    def requests_for(self, uid: str) -> list[ProductRequest]:
        with self._conn() as c:
            rows = c.execute("SELECT * FROM product_requests WHERE user_id=? ORDER BY created_at DESC", (uid,)).fetchall()
        return [_req(r) for r in rows]

    def all_requests(self, status: str | None = None) -> list[ProductRequest]:
        q, args = "SELECT * FROM product_requests", ()
        if status:
            q, args = q + " WHERE status=?", (status,)
        with self._conn() as c:
            rows = c.execute(q + " ORDER BY created_at", args).fetchall()
        return [_req(r) for r in rows]

    def review_request(self, rid: str, status: str, admin_note: str = "", product_id: str | None = None) -> ProductRequest | None:
        if status not in ("approved", "rejected"):
            raise ValueError("status must be approved or rejected")
        with self._conn() as c:
            c.execute("UPDATE product_requests SET status=?, admin_note=?, product_id=?, reviewed_at=? WHERE id=?",
                      (status, admin_note.strip(), product_id, time.time(), rid))
            r = c.execute("SELECT * FROM product_requests WHERE id=?", (rid,)).fetchone()
        return _req(r) if r else None
