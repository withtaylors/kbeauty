"""
저장소 (SQLite) — 사용자별 장바구니·설정·판결 기록

로그인은 아직 없습니다. 지금은 기기마다 익명 user_id(UUID)를 발급해 저장하고,
나중에 로그인을 붙이면 users 테이블에 이메일/소셜 ID를 채우고
같은 user_id를 그대로 쓰거나 merge_users()로 익명 기록을 옮기면 됩니다.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

DB_PATH = Path(os.getenv("CARTCOURT_DB", Path(__file__).parent.parent / "data" / "cartcourt.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id          TEXT PRIMARY KEY,
  created_at  REAL NOT NULL,
  email       TEXT UNIQUE,          -- 로그인 붙일 때 사용 (지금은 NULL)
  provider    TEXT,                 -- kakao | google | email ...
  provider_id TEXT
);
CREATE TABLE IF NOT EXISTS settings (
  user_id   TEXT PRIMARY KEY REFERENCES users(id),
  budget    INTEGER NOT NULL DEFAULT 200000,
  payments  TEXT NOT NULL DEFAULT '[]',
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS items (
  id         TEXT PRIMARY KEY,
  user_id    TEXT NOT NULL REFERENCES users(id),
  data       TEXT NOT NULL,         -- 상품 JSON (name, platform, price, image, color_hex, category, ...)
  status     TEXT NOT NULL DEFAULT 'active',   -- active | bought | dropped
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_items_user ON items(user_id, status, created_at);
CREATE TABLE IF NOT EXISTS verdicts (
  id         TEXT PRIMARY KEY,
  user_id    TEXT NOT NULL REFERENCES users(id),
  case_no    TEXT NOT NULL,
  data       TEXT NOT NULL,         -- 판결 전체 JSON (재현용)
  final_total INTEGER, discount INTEGER, rejected_amount INTEGER,
  accepted   INTEGER NOT NULL DEFAULT 0,   -- 판결 집행 여부 (누적 금액은 집행된 판결만)
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_verdicts_user ON verdicts(user_id, created_at);
"""


@contextmanager
def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init():
    with db() as c:
        c.executescript(SCHEMA)


def now() -> float:
    return time.time()


# ---------- 사용자 ----------

def ensure_user(user_id: Optional[str]) -> str:
    """헤더로 받은 id가 유효하면 그대로, 없으면 새 익명 사용자 생성."""
    with db() as c:
        if user_id:
            row = c.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone()
            if row:
                return row["id"]
        uid = user_id if (user_id and len(user_id) <= 64) else uuid.uuid4().hex
        c.execute("INSERT OR IGNORE INTO users(id, created_at) VALUES(?,?)", (uid, now()))
        c.execute("INSERT OR IGNORE INTO settings(user_id, updated_at) VALUES(?,?)", (uid, now()))
        return uid


def merge_users(from_id: str, to_id: str):
    """(로그인 이후용) 익명 기록을 로그인 계정으로 옮김."""
    with db() as c:
        c.execute("UPDATE items SET user_id=? WHERE user_id=?", (to_id, from_id))
        c.execute("UPDATE verdicts SET user_id=? WHERE user_id=?", (to_id, from_id))


# ---------- 설정 ----------

def get_settings(uid: str) -> dict:
    with db() as c:
        r = c.execute("SELECT budget, payments, updated_at FROM settings WHERE user_id=?", (uid,)).fetchone()
    return {"budget": r["budget"], "payments": json.loads(r["payments"]), "configured": bool(json.loads(r["payments"]))}


def save_settings(uid: str, budget: int, payments: list) -> dict:
    with db() as c:
        c.execute("INSERT INTO settings(user_id,budget,payments,updated_at) VALUES(?,?,?,?) "
                  "ON CONFLICT(user_id) DO UPDATE SET budget=excluded.budget, payments=excluded.payments, updated_at=excluded.updated_at",
                  (uid, int(budget), json.dumps(payments), now()))
    return get_settings(uid)


# ---------- 장바구니 ----------

def list_items(uid: str, status: str = "active") -> list:
    with db() as c:
        rows = c.execute("SELECT id, data, status, created_at FROM items WHERE user_id=? AND status=? ORDER BY created_at",
                         (uid, status)).fetchall()
    out = []
    for r in rows:
        d = json.loads(r["data"])
        d.update({"id": r["id"], "status": r["status"], "created_at": r["created_at"]})
        out.append(d)
    return out


def add_item(uid: str, data: dict) -> dict:
    iid = data.get("id") or uuid.uuid4().hex[:10]
    data = {k: v for k, v in data.items() if k not in ("id", "status", "created_at")}
    with db() as c:
        # 같은 링크가 이미 있으면 갱신
        if data.get("url"):
            for r in c.execute("SELECT id, data FROM items WHERE user_id=? AND status='active'", (uid,)).fetchall():
                if json.loads(r["data"]).get("url") == data["url"]:
                    iid = r["id"]
                    break
        c.execute("INSERT INTO items(id,user_id,data,status,created_at,updated_at) VALUES(?,?,?,?,?,?) "
                  "ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
                  (iid, uid, json.dumps(data, ensure_ascii=False), "active", now(), now()))
    data.update({"id": iid, "status": "active"})
    return data


def update_item(uid: str, iid: str, patch: dict) -> Optional[dict]:
    with db() as c:
        r = c.execute("SELECT data FROM items WHERE id=? AND user_id=?", (iid, uid)).fetchone()
        if not r:
            return None
        d = json.loads(r["data"])
        d.update({k: v for k, v in patch.items() if k not in ("id", "status", "created_at")})
        c.execute("UPDATE items SET data=?, updated_at=? WHERE id=? AND user_id=?",
                  (json.dumps(d, ensure_ascii=False), now(), iid, uid))
    d["id"] = iid
    return d


def set_item_status(uid: str, iid: str, status: str) -> bool:
    assert status in ("active", "bought", "dropped")
    with db() as c:
        cur = c.execute("UPDATE items SET status=?, updated_at=? WHERE id=? AND user_id=?", (status, now(), iid, uid))
        return cur.rowcount > 0


def delete_item(uid: str, iid: str) -> bool:
    with db() as c:
        return c.execute("DELETE FROM items WHERE id=? AND user_id=?", (iid, uid)).rowcount > 0


# ---------- 판결 기록 ----------

def save_verdict(uid: str, verdict: dict) -> str:
    vid = uuid.uuid4().hex[:10]
    with db() as c:
        c.execute("INSERT INTO verdicts(id,user_id,case_no,data,final_total,discount,rejected_amount,created_at) VALUES(?,?,?,?,?,?,?,?)",
                  (vid, uid, verdict["case_no"], json.dumps(verdict, ensure_ascii=False),
                   verdict["final_total"], verdict["discount"], verdict["rejected_amount"], now()))
    return vid


def list_verdicts(uid: str, limit: int = 50) -> list:
    with db() as c:
        rows = c.execute("SELECT id, case_no, final_total, discount, rejected_amount, accepted, created_at, data FROM verdicts "
                         "WHERE user_id=? ORDER BY created_at DESC LIMIT ?", (uid, limit)).fetchall()
    out = []
    for r in rows:
        d = json.loads(r["data"])
        out.append({"id": r["id"], "case_no": r["case_no"], "final_total": r["final_total"], "discount": r["discount"],
                    "rejected_amount": r["rejected_amount"], "created_at": r["created_at"], "accepted": bool(r["accepted"]),
                    "approved_count": len(d.get("approved", [])), "rejected_count": len(d.get("rejected", []))})
    return out


def get_verdict(uid: str, vid: str) -> Optional[dict]:
    with db() as c:
        r = c.execute("SELECT data FROM verdicts WHERE id=? AND user_id=?", (vid, uid)).fetchone()
    return json.loads(r["data"]) if r else None


def accept_verdict(uid: str, vid: str) -> Optional[dict]:
    """판결 집행: 허가 상품 → bought, 기각 상품 → dropped. 누적 금액은 집행된 판결만 합산."""
    v = get_verdict(uid, vid)
    if not v:
        return None
    with db() as c:
        already = c.execute("SELECT accepted FROM verdicts WHERE id=?", (vid,)).fetchone()["accepted"]
        if already:
            return {"ok": True, "already": True}
        for it in v.get("approved", []):
            c.execute("UPDATE items SET status='bought', updated_at=? WHERE id=? AND user_id=?", (now(), it["id"], uid))
        for r in v.get("rejected", []):
            c.execute("UPDATE items SET status='dropped', updated_at=? WHERE id=? AND user_id=?", (now(), r["item"]["id"], uid))
        c.execute("UPDATE verdicts SET accepted=1 WHERE id=? AND user_id=?", (vid, uid))
    return {"ok": True, "already": False}


def totals(uid: str) -> dict:
    """누적: 집행된 판결로 지켜낸 금액 (같은 장바구니 재심을 중복 집계하지 않음)."""
    with db() as c:
        r = c.execute("SELECT COUNT(*) n, COALESCE(SUM(discount),0) d, COALESCE(SUM(rejected_amount),0) rj "
                      "FROM verdicts WHERE user_id=? AND accepted=1", (uid,)).fetchone()
        t = c.execute("SELECT COUNT(*) n FROM verdicts WHERE user_id=?", (uid,)).fetchone()
    return {"trials": t["n"], "executed": r["n"], "discount": r["d"], "rejected": r["rj"], "saved": r["d"] + r["rj"]}
