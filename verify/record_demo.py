"""
Record the demo video by driving the real app in a phone-sized browser.

    pip install playwright && playwright install chromium      (once)
    uvicorn app:app --port 8000                                 (in another terminal, with your .env)
    python verify/record_demo.py                                → verify/demo.mp4 (+ demo.webm)

Options (environment variables):
    DEMO_URL     app address            default http://localhost:8000
    DEMO_PHOTO   a product photo to upload in the photo scene (e.g. verify/photos/romand-glasting-melting-balm_1.png).
                 Needs OPENAI_API_KEY on the server; skipped when unset.
    DEMO_LIVE    a query for the live (Olive Young) search scene, e.g. "토리든 다이브인". Needs NAVER keys; skipped when unset.
    DEMO_LANG    app language for the tourist persona, default en
    DEMO_CAPTION ko (default) — caption language for the viewer (the class), or en

The script only clicks what a user would click; nothing is faked.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import time
from pathlib import Path

from playwright.async_api import Page, async_playwright

URL = os.getenv("DEMO_URL", "http://localhost:8000")
PHOTO = os.getenv("DEMO_PHOTO", "")
LIVE_Q = os.getenv("DEMO_LIVE", "")
LANG = os.getenv("DEMO_LANG", "en")
CAP = os.getenv("DEMO_CAPTION", "ko")
OUT = Path(__file__).parent

CAPTIONS = {
    "ko": {
        "setup": "① 3번만 누르면 준비 끝 — 언어 · 본국 통화 · 피부 타입",
        "photo": "② 매대 제품을 찍거나 갤러리에서 고르면 AI가 제품을 식별",
        "search": "② 이름으로도 검색 — 큐레이션 DB와 올리브영 실시간 결과가 한 목록에",
        "live": "올리브영 실시간 상품 (네이버 쇼핑 API) — 본국 가격이 없으면 '판결 보류'로 정직하게",
        "detail": "③ 상세: 내 언어 설명 · 피부 적합 · 오늘 환율로 한국 vs 본국 가격",
        "court": "④ 재판소 판결 — 규칙(R5)이 선고하고 이유를 씀. AI가 아니라 계산",
        "shelf": "⑤ 매대 가격이 다르면 직접 입력 → 다시 판결 → 결과가 뒤집힘",
        "dup": "⑥ 비슷한 제품을 또 담으면 중복 경고 — 추천이 아니라 말리는 쪽",
        "list": "⑦ 리스트는 폰에 저장 — 앱을 닫아도 남음",
        "trip": "⑧ 여행 정산 — 택스리펀 예상액 · 실제 결제액 · 본국 대비 절약, 계산 근거까지",
        "request": "⑨ DB에 없는 제품은 추가 요청 → 운영자가 검수 후 결과 표시",
        "end": "K-Beauty Scan — 박지연 · 01분반",
    },
    "en": {
        "setup": "① Three taps: language · home currency · skin type",
        "photo": "② Snap a product or pick from the gallery — AI identifies it",
        "search": "② Or search by name — curated DB and live Olive Young results in one list",
        "live": "Live Olive Young listing (Naver Shopping API) — no home price → ruling deferred, honestly",
        "detail": "③ Detail: description in your language · skin fit · Korea vs home at today's rate",
        "court": "④ The Court rules — a rule (R5) decides and writes its reasons. Math, not AI",
        "shelf": "⑤ Different shelf price? Type it → re-judge → the ruling flips",
        "dup": "⑥ Add something similar → duplicate warning. Not a recommender",
        "list": "⑦ Your list is saved on the phone",
        "trip": "⑧ Trip summary — tax refund · what you actually pay · savings vs home, with the math",
        "end": "K-Beauty Scan — Jiyeon Park · section 01",
    },
}[CAP]

CAPTION_CSS = """
#demo-cap{position:fixed;left:12px;right:12px;bottom:14px;z-index:9999;background:rgba(0,0,0,.86);color:#fff;
 font:600 14px/1.45 -apple-system,'Pretendard','Noto Sans KR',sans-serif;padding:12px 16px;border-radius:14px;
 opacity:0;transition:opacity .35s;pointer-events:none;letter-spacing:-.01em}
#demo-cap.on{opacity:1}
#demo-cursor{position:fixed;z-index:10000;width:22px;height:22px;border-radius:50%;background:rgba(0,0,0,.25);
 border:2px solid #000;transform:translate(-50%,-50%);pointer-events:none;transition:left .25s,top .25s;opacity:0}
#demo-cursor.on{opacity:1}
"""


async def install_overlay(page: Page) -> None:
    await page.add_style_tag(content=CAPTION_CSS)
    await page.evaluate("""() => {
      if (!document.getElementById('demo-cap')) {
        const c = document.createElement('div'); c.id = 'demo-cap'; document.body.appendChild(c);
        const k = document.createElement('div'); k.id = 'demo-cursor'; document.body.appendChild(k);
      }}""")


async def caption(page: Page, key: str, hold: float = 1.6) -> None:
    await install_overlay(page)
    await page.evaluate("""(txt) => { const c = document.getElementById('demo-cap'); c.textContent = txt; c.classList.add('on'); }""", CAPTIONS[key])
    await page.wait_for_timeout(int(hold * 1000))


async def tap(page: Page, selector: str, after: float = 0.9) -> None:
    """Move a visible cursor to the element, pause, click — so viewers can follow."""
    el = page.locator(selector).first
    await el.scroll_into_view_if_needed()
    box = await el.bounding_box()
    if box:
        await page.evaluate("""([x, y]) => { const k = document.getElementById('demo-cursor'); k.style.left = x + 'px'; k.style.top = y + 'px'; k.classList.add('on'); }""",
                            [(box["x"] + box["width"] / 2) / 2, (box["y"] + box["height"] / 2) / 2])
        await page.wait_for_timeout(450)
    await el.click()
    await page.wait_for_timeout(int(after * 1000))


async def type_slow(page: Page, selector: str, text: str) -> None:
    await page.click(selector)
    await page.fill(selector, "")
    await page.type(selector, text, delay=70)
    await page.wait_for_timeout(400)


async def run() -> Path:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        # Playwright records at the viewport's size, so render a phone layout at 2× for a crisp 780×1688 video.
        ctx = await browser.new_context(viewport={"width": 780, "height": 1688}, device_scale_factor=1,
                                        record_video_dir=str(OUT / "_video"), record_video_size={"width": 780, "height": 1688})
        page = await ctx.new_page()
        await page.add_init_script("document.addEventListener('DOMContentLoaded', () => { document.documentElement.style.zoom = '2'; });")
        await page.goto(URL)
        await page.wait_for_selector(".view.on")
        await page.wait_for_timeout(800)

        # ① setup
        await caption(page, "setup")
        await tap(page, f'.chip[data-v="{LANG}"]', 0.5)
        await tap(page, '.chip[data-v="USD"]', 0.5)
        await tap(page, '.chip[data-v="sensitive"]', 0.5)
        await tap(page, "#btn-save-profile", 1.2)
        await page.wait_for_selector("#v-scan.on")

        # ② photo (needs a vision key on the server)
        if PHOTO and Path(PHOTO).exists():
            await caption(page, "photo")
            await page.set_input_files("#file-gallery", PHOTO)
            await page.wait_for_selector(".pc, .rs", timeout=90_000)
            await page.wait_for_timeout(2600)
            if await page.locator(".rs").count():            # ambiguous → pick the first candidate
                await tap(page, ".rs", 1.5)
            await page.wait_for_timeout(1500)
            await page.evaluate("document.getElementById('result').innerHTML = ''")
            await page.evaluate("window.scrollTo(0, 0)")

        # ② name search → results list
        await caption(page, "search")
        await type_slow(page, "#q", "anua")
        await page.keyboard.press("Enter")
        await page.wait_for_selector(".rs")
        await page.wait_for_timeout(2000)

        if LIVE_Q and await page.locator(".rs .src.live").count() == 0:
            await type_slow(page, "#q", LIVE_Q)
            await page.keyboard.press("Enter")
            await page.wait_for_selector(".rs")
            await page.wait_for_timeout(1500)
        if await page.locator(".rs .src.live").count():
            await caption(page, "live")
            await tap(page, ".rs:has(.src.live)", 1.2)
            await page.wait_for_selector(".court")
            await page.wait_for_timeout(2600)
            await tap(page, "#btn-back", 1.0)
            await page.wait_for_selector(".rs")

        # ③ detail + ④ court
        await caption(page, "detail")
        await tap(page, ".rs:has(.src.catalog)", 1.2)
        await page.wait_for_selector(".court")
        await page.wait_for_timeout(1800)
        await caption(page, "court")
        await page.locator(".court").scroll_into_view_if_needed()
        await page.wait_for_timeout(2600)

        # ⑤ shelf price → ruling flips
        await caption(page, "shelf")
        await type_slow(page, "form[data-shelf] input", "45000")
        await tap(page, "form[data-shelf] button", 1.0)
        await page.wait_for_selector(".court.buy_home, .court.similar", timeout=10_000)
        await page.locator(".court").scroll_into_view_if_needed()
        await page.wait_for_timeout(2800)
        # back to the catalog price before adding
        await type_slow(page, "form[data-shelf] input", "28000")
        await tap(page, "form[data-shelf] button", 1.0)
        await page.wait_for_selector(".court.buy_here, .court.similar", timeout=10_000)
        await tap(page, "[data-add]", 1.4)

        # ⑥ duplicate warning
        await caption(page, "dup")
        await page.evaluate("window.scrollTo(0, 0)")
        # SoonJung toner shares category + 2 tags (soothing, panthenol) with the Anua toner → R3 warning
        await type_slow(page, "#q", "soonjung toner")
        await page.keyboard.press("Enter")
        await page.wait_for_selector(".rs")
        await page.wait_for_timeout(1200)
        await tap(page, ".rs:has(.src.catalog)", 1.2)
        await page.wait_for_selector(".pc")
        if await page.locator(".dup").count():
            await page.locator(".dup").scroll_into_view_if_needed()
        await page.wait_for_timeout(2400)
        await tap(page, "[data-add]", 1.2)

        # ⑦ list
        await caption(page, "list")
        await tap(page, '.tabs [data-v="list"]', 1.0)
        await page.wait_for_selector(".li")
        await page.wait_for_timeout(2000)

        # ⑧ trip summary
        await caption(page, "trip")
        await tap(page, '[data-go="trip"]', 1.0)
        await page.wait_for_selector(".hero")
        await page.wait_for_timeout(2400)
        await page.mouse.wheel(0, 500)
        await page.wait_for_timeout(2400)

        # ⑨ request a missing product
        if "request" in CAPTIONS:
            await caption(page, "request")
            await tap(page, '.tabs [data-v="scan"]', 0.6)
            await page.evaluate("window.scrollTo(0, 0)")
            await type_slow(page, "#q", "heroine make eyeliner")
            await page.keyboard.press("Enter")
            await page.wait_for_selector("#btn-request")
            await page.wait_for_timeout(1200)
            await tap(page, "#btn-request", 0.8)
            await type_slow(page, "#req-form [name=brand]", "KissMe")
            await tap(page, "#req-form button[type=submit]", 1.2)
            await tap(page, '.tabs [data-v="list"]', 0.8)
            await page.wait_for_selector(".rq")
            await page.locator(".rq").scroll_into_view_if_needed()
            await page.wait_for_timeout(2200)

        await caption(page, "end", 2.4)
        await ctx.close()
        video = await page.video.path()
        await browser.close()
    return Path(video)


def to_mp4(webm: Path) -> Path | None:
    if not shutil.which("ffmpeg"):
        print("ffmpeg not found — keeping", webm)
        return None
    mp4 = OUT / "demo.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(webm), "-vf", "scale=780:-2,fps=30",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "22", "-movflags", "+faststart", str(mp4)], check=True)
    return mp4


if __name__ == "__main__":
    t0 = time.time()
    webm = asyncio.run(run())
    final = OUT / "demo.webm"
    shutil.move(str(webm), final)
    shutil.rmtree(OUT / "_video", ignore_errors=True)
    mp4 = to_mp4(final)
    print(f"done in {time.time() - t0:.0f}s → {mp4 or final}")
