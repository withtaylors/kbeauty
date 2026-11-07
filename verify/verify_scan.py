"""
Verification #1 — photo identification accuracy.

Usage
    python verify/verify_scan.py --ids        # list catalog ids
    python verify/verify_scan.py              # run against verify/photos/

Photos go in verify/photos/ named  <product-id>_<n>.jpg|png
    e.g.  anua-heartleaf-toner_1.jpg
For a product that is NOT in the catalog use  none-<anything>_<n>.jpg ;
it passes when the app does not confidently claim a wrong product.
An API failure (e.g. 429) is reported as "error" and never counted as a pass.

Needs an image-capable key in .env (OPENAI_API_KEY or ANTHROPIC_API_KEY).
Writes verify/verify_scan.json for the slides.
"""
from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import app as appmod  # noqa: E402

PHOTOS = ROOT / "verify" / "photos"
PAUSE_S = 3
RETRIES = 2
QUOTA_HELP = """
   → API 계정에 사용 가능한 크레딧이 없습니다 (insufficient_quota / credit_balance_exhausted).
     platform.openai.com → Settings → Billing 에서 결제 수단을 등록하고 크레딧을 충전한 뒤
     몇 분 기다렸다가 다시 실행하세요. 같은 키를 그대로 쓰면 됩니다."""
OUT = ROOT / "verify" / "verify_scan.json"


def _retryable(err: str) -> bool:
    """Only a per-minute rate limit is worth waiting for."""
    return err.startswith("429") and "rate_limit" in err


def _out_of_credit(err: str) -> bool:
    """429 that is not a rate limit = billing problem (insufficient_quota, credit_balance_exhausted, ...)."""
    return err.startswith("429") and not _retryable(err) or any(w in err for w in ("quota", "credit", "billing"))


def main() -> int:
    with TestClient(appmod.app) as client:
        ctx = appmod.app.state.ctx
        if "--ids" in sys.argv:
            print("\n".join(p.id for p in ctx.catalog))
            return 0
        photos = sorted(p for p in PHOTOS.glob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"})
        if not photos:
            print(f"no photos in {PHOTOS} (name them <product-id>_<n>.jpg)")
            return 1
        if not ctx.vision.enabled:
            print("no image-capable API key in .env (OPENAI_API_KEY or ANTHROPIC_API_KEY)")
            return 1

        headers = {"X-User-Id": "verifybot"}
        rows, exact, top3, errors = [], 0, 0, 0
        for i, ph in enumerate(photos):
            if i:
                time.sleep(PAUSE_S)                     # stay under per-minute limits on new accounts
            truth = ph.stem.rsplit("_", 1)[0]
            mime = "image/png" if ph.suffix.lower() == ".png" else "image/jpeg"
            data_url = f"data:{mime};base64," + base64.b64encode(ph.read_bytes()).decode()
            t0 = time.time()
            for attempt in range(RETRIES + 1):
                r = client.post("/api/scan", json={"image_b64": data_url}, headers=headers).json()
                err = r.get("error") if r.get("method") == "vision_error" else None
                if not err or not _retryable(err) or attempt == RETRIES:
                    break
                wait = 20 * (attempt + 1)
                print(f"   {ph.name}: {err} — rate limited, retrying in {wait}s")
                time.sleep(wait)
            if err:
                errors += 1
                rows.append({"photo": ph.name, "truth": truth, "status": "error", "error": err, "correct": None,
                             "seconds": round(time.time() - t0, 1)})
                print("⚠️ ", ph.name, "→ API error", err, "(판정 불가)")
                if _out_of_credit(err):
                    print(QUOTA_HELP)
                    break
                continue
            got = r["card"]["product"]["id"] if r["status"] == "ok" else None
            cands = [c["id"] for c in r.get("candidates", [])]
            if truth.startswith("none"):
                hit = hit3 = got is None
            else:
                hit = got == truth
                hit3 = hit or truth in cands
            exact += hit
            top3 += hit3
            rows.append({"photo": ph.name, "truth": truth, "status": r["status"], "got": got, "candidates": cands,
                         "confidence": r.get("confidence"), "correct": hit, "correct_in_top3": hit3,
                         "seconds": round(time.time() - t0, 1)})
            print("✅" if hit else "🟡" if hit3 else "❌", ph.name, "→", got or cands or r.get("error"))

        n = len(rows) - errors                                  # only photos the model actually answered
        if n == 0:
            print("\nno photo was judged — every request failed. Nothing written.")
            return 2
        result = {"tested": n, "api_errors": errors, "correct": exact, "accuracy_pct": round(exact / n * 100, 1),
                  "correct_in_top3": top3, "top3_accuracy_pct": round(top3 / n * 100, 1),
                  "target": "≥ 80%", "model": ctx.settings.openai_model if ctx.settings.openai_api_key else ctx.settings.anthropic_model,
                  "rows": rows}
        with OUT.open("w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=1)
        in_db = [x for x in rows if x.get("correct") is not None and not x["truth"].startswith("none")]
        out_db = [x for x in rows if x.get("correct") is not None and x["truth"].startswith("none")]
        print(f"\nDB 안 {len(in_db)}장 중 {sum(x['correct'] for x in in_db)}장 식별 · "
              f"DB 밖 {len(out_db)}장 중 {sum(x['correct'] for x in out_db)}장 올바르게 거절 · API 오류 {errors}장(판정 불가)")
        print(f"exact {exact}/{n} = {result['accuracy_pct']}%   top-3 {top3}/{n} = {result['top3_accuracy_pct']}%")
        print(f"→ {OUT.relative_to(ROOT)}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
