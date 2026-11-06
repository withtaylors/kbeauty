"""검증 ① 수집 성공률: urls.txt 링크를 돌려 성공/실패를 기록합니다 (슬라이드 근거용)."""
import asyncio, json, sys, time
from cartcourt.scraper import fetch_product

async def main():
    urls = [l.strip() for l in open("urls.txt", encoding="utf-8") if l.strip() and not l.startswith("#")]
    rows, t0 = [], time.time()
    for u in urls:
        r = await fetch_product(u)
        rows.append({"url": u, "platform": r.get("platform"), "ok": r.get("ok"), "name": r.get("name"),
                     "price": r.get("price"), "image": bool(r.get("image")), "reason": r.get("reason")})
        print(("✅" if r.get("ok") else "❌"), r.get("platform"), "|", r.get("name"), "|", r.get("price"), "|", r.get("reason") or "")
    ok = sum(1 for x in rows if x["ok"])
    summary = {"tested": len(rows), "ok": ok, "rate": round(ok / max(len(rows), 1) * 100, 1), "seconds": round(time.time() - t0, 1), "rows": rows}
    json.dump(summary, open("verify_result.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n수집 성공률 {ok}/{len(rows)} = {summary['rate']}%  → verify_result.json 저장")

asyncio.run(main())
