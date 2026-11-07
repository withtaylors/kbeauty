# K-Beauty Scan

외국인 관광객이 한국 매장에서 K-뷰티 제품을 찍으면, **내 언어로** 무슨 제품인지 · 내 피부에 맞는지 · 본국보다 얼마 싼지 · 이미 담은 것과 겹치는지 알려주고, 여행이 끝나면 **택스리펀 예상액과 귀국 후 재구매 목록**까지 정리해 주는 모바일 웹.

- 언어: English · 한국어 / 본국 통화: USD · JPY
- **재판소 판결(R5)**: 오늘 환율로 한국 가격 vs 본국 가격을 비교해 "지금 여기서 사세요 / 본국에서 사세요 / 큰 차이 없음 / 판결 보류(본국 가격 미확인)"를 이유와 함께 선고. 매대 가격이 DB와 다르면 **매대 가격을 직접 입력**해 다시 판결
- 환율: 서버 시작·6시간마다 ECB 기준 실시간 환율(Frankfurter, 무료·키 없음) 자동 반영, 실패하면 `rules.json` 참고값. 카드 하단에 "실시간 환율/참고 환율 · 기준일" 표시
- 찾는 방법 두 가지: **① 사진(카메라·갤러리)** 또는 **② 이름 검색** → 결과 목록에서 고르면 상세 페이지
- DB에 없는 제품은 앱에서 **추가 요청** → 운영자가 `python manage.py requests`로 보고 `approve`/`reject` → 사용자는 리스트 탭 "내 요청"에서 결과(추가됨·추가 안 됨·메모)를 봄
- 제품 데이터 두 층: 큐레이션 DB 43개(본국 가격·성분 태그 있음, `kbeauty/products.json`) + **올리브영 실시간 검색**(네이버 쇼핑 API, 올리브영 판매 상품만 필터). 실시간 제품은 본국 가격이 없으므로 "아직 DB에 없어요"라고 정직하게 표시하고, 정산에서는 본국 가격이 있는 제품만으로 절약액을 계산

## ChatGPT와 다른 점 · 추천 시스템이 아닌 이유

| | ChatGPT에 사진 보내기 | K-Beauty Scan |
|---|---|---|
| 제품 식별 | 됨 | 됨 (AI, 제품 DB 안에서 고름) |
| 한국가 vs 본국가 | 모름 / 매번 다름 | **제품 DB + 환율표로 계산**, 같은 입력이면 같은 결과 |
| 내 쇼핑 리스트 | 없음 | 여행 내내 저장, **이미 담은 것과 중복 경고** |
| 택스리펀 | 규칙 설명만 | **매장별 합계로 예상 환급액 계산** (₩15,000 기준, 구간 환급률) |
| 근거 | 말로 설명 | **"How we calculated"**: 모든 숫자의 계산식 공개 |

새 제품을 권하지 않습니다. 손에 든 제품을 번역·판별·비교하는 **통역사**이고, 비슷한 걸 이미 담았거나 본국이 더 싸면 그대로 알려 줍니다(덜 사게 함).

**AI는 한 곳만**: 사진 → 43개 중 어느 제품인지. 가격·피부 적합도·중복·택스리펀은 `kbeauty/engine.py`의 규칙이 계산합니다.

## 실행 (Windows PowerShell)

```powershell
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest                                     # 44 passed
ruff check .                               # (선택) 린트
uvicorn app:app --reload --port 8000       # → http://localhost:8000
```

Mac: `source .venv/bin/activate`. 휴대폰으로 보려면 `--host 0.0.0.0` 후 같은 와이파이에서 `http://노트북IP:8000`.

**사진 인식을 쓰려면** 프로젝트 폴더에 `.env` 파일을 만들고 넣으세요 (키 없이도 이름 검색으로 전체 흐름은 동작):
```
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o
```
`OPENAI_MODEL`을 빼면 `gpt-4o-mini`(저렴, 정확도 낮을 수 있음). Anthropic 키를 쓰려면 `ANTHROPIC_API_KEY=`.
`.env`는 `.gitignore`에 있어 GitHub에 올라가지 않습니다.

**실제 올리브영 상품 검색을 쓰려면** (무료) [developers.naver.com](https://developers.naver.com) → 애플리케이션 등록 → 사용 API "검색" 체크 → 발급된 Client ID/Secret을 `.env`에:
```
NAVER_CLIENT_ID=...
NAVER_CLIENT_SECRET=...
```
키가 없으면 검색 결과에 큐레이션 DB만 나오고 화면에 "실시간 검색이 꺼져 있어요"라고 표시됩니다. `LIVE_OLIVE_YOUNG_ONLY=0`이면 네이버 쇼핑의 모든 몰을 보여줍니다.

## DB에 없는 제품: 이름 + 매대 가격으로 바로 판결 (웹 가격 검색)

검색 결과 아래 "목록에 없나요? 바로 판결받기"에 제품 이름과 매대 가격을 넣으면,
본국 가격을 웹에서 찾아 같은 규칙으로 판결합니다. GPT·Claude가 인터넷을 검색하는 방식과 같지만, **가격은 AI가 만들지 않습니다.**

1. 검색 API(Tavily)로 "브랜드 + 제품명 + price" 검색 (본국 국가 우선)
2. 결과 본문에서 가격을 **정규식으로** 추출 — 원문에 실제로 있는 숫자만
3. 한국 사이트 제외, 제품명이 맞는 결과만, 한국 가격의 0.5~4배 범위만, 도메인당 1개
4. **서로 다른 출처 2곳 이상**일 때만 중간값을 본국 가격으로 사용, 화면에 출처 링크 표시
5. 조건을 못 채우면 추측하지 않고 "판결 보류"

키 발급: [tavily.com](https://tavily.com) 가입 → API 키를 `.env`의 `TAVILY_API_KEY=`에. 무료 월 1,000회, 카드 등록 없음. 같은 제품은 하루 동안 다시 검색하지 않아 무료 한도로 충분합니다.
큐레이션 DB 제품은 웹 검색을 하지 않고 DB 가격을 그대로 씁니다.

## 무료 운영 구성

| 부분 | 무엇으로 | 비용 |
|---|---|---|
| 서버 | Render 무료 웹 서비스 (15분 미접속 시 잠들고, 첫 접속 약 1분) | 무료 |
| 환율 | Frankfurter (ECB 기준환율, 키 없음) | 무료 |
| 본국 가격 웹 검색 | Tavily 무료 플랜 (월 1,000회) | 무료 |
| 사진 식별 | OpenAI API (사진 1장당 호출 1회) | 사용량만큼 |
| 사용자 데이터 | 지금 SQLite. 배포 시 무료 외부 DB로 이전 예정 (무료 호스팅은 파일이 재시작 때 지워짐) | 무료 |

## 데모 영상 자동 녹화

```powershell
pip install playwright
playwright install chromium
uvicorn app:app --port 8000          # 다른 터미널, .env 키 포함
$env:DEMO_PHOTO="verify/photos/romand-glasting-melting-balm_1.png"   # 사진 인식 장면 (OpenAI 키 필요)
$env:DEMO_LIVE="토리든 다이브인"                                       # 올리브영 실시간 장면 (네이버 키 필요)
python verify/record_demo.py          # → verify/demo.mp4 (약 90초, 한글 자막)
```
스크립트는 실제 앱을 사용자처럼 눌러 보기만 하고, 아무것도 꾸미지 않습니다.

## 제품 추가 요청 검수 (운영자)

```powershell
python manage.py requests                       # 검토 대기 목록 (id, 브랜드, 이름, 메모)
python manage.py skeleton <id>                  # products.json에 붙여 넣을 JSON 틀 출력
#   → kbeauty/products.json 에 제품 추가 (가격·태그 채우기) → 서버 재시작
python manage.py approve <id> <product-id> --note "11/06 추가"
python manage.py reject  <id> --note "단종 제품"
```
승인하면 사용자 화면에 "추가됨 · 열기" 버튼이 생겨 바로 상세 페이지로 갑니다.

## 검증

| # | 항목 | 기준 | 방법 |
|---|---|---|---|
| ① | 사진 식별 정확도 | 80% 이상 | 실물 사진 5장(DB 안 3 + DB 밖 2)이 `verify/photos/`에 있음 → `python verify/verify_scan.py` → `verify/verify_scan.json`. DB 밖 제품(`none-…`)은 엉뚱한 제품을 확신하지 않으면 통과 |
| ② | 계산 정확도 | 손계산과 오차 0 | `pytest -q` — 기대값이 전부 손계산 값 (`tests/test_engine.py` 주석) |
| ③ | 사용자 반응 | "매장에서 쓰겠다" 과반 | `verify/questionnaire.md` — 현재 **AI 대리 평가**(영어 사용자 역할), 발견된 문제 1건 수정 |

## 구조

```
manage.py              운영자 콘솔 — 제품 추가 요청 검수 (승인/반려/JSON 틀)
app.py                 HTTP 계층 (FastAPI). 요청 검증(pydantic), 응답 조립만. 도메인 로직 없음
kbeauty/config.py      Settings (환경변수·.env → 불변 객체)
kbeauty/catalog.py     Product · Rules 타입 + 검증 로더 (Catalog)
kbeauty/engine.py      계산 엔진 — 순수 함수, dataclass 결과, 근거 문자열. AI 없음
kbeauty/vision.py      식별 — TextSearch(결정론) · VisionIdentifier(OpenAI/Anthropic 교체 가능) · 이미지 검증
kbeauty/fx.py          실시간 환율 — Frankfurter(ECB) 클라이언트, TTL 캐시, 실패 시 rules.json 유지
kbeauty/webprice.py    웹 가격 검색 — Tavily 클라이언트, 정규식 가격 추출, 출처 2곳 이상 규칙, 하루 캐시
kbeauty/sources.py     실시간 소스 — 네이버 쇼핑 API 클라이언트, 올리브영 필터, 제목→카테고리/성분 태그(키워드 표), TTL 캐시
kbeauty/i18n.py        en/ko 번역표, 규칙 기반 설명 문장
kbeauty/store.py       SQLite 저장소 클래스 (UNIQUE 제약·FK·트랜잭션, 로그인 전환용 merge_users)
kbeauty/products.json  제품 43개 / kbeauty/rules.json 환율·택스리펀·중복 규칙 (기준일 포함)
static/index.html      마크업만 / static/app.js  api → state → render → events / static/i18n.js  UI 문자열 / static/styles.css
tests/                 25개: 엔진(손계산 대조) · 식별(가짜 provider로 파싱·폴백) · API(검증·사용자 분리)
verify/                식별 정확도 스크립트 · 사용자 질문지
.github/workflows/ci.yml  push마다 ruff + pytest
```

### 설계 원칙
- **AI 경계를 코드로 고정**: LLM은 `vision.py`의 `VisionProvider` 인터페이스 뒤에만 있고, 반환값은 "카탈로그 id + 확신도"뿐. 가격·성분·적합도는 LLM이 만들 수 없음
- **결정론**: `engine.py`는 입력이 같으면 출력이 같음. 모든 숫자에 계산식(`evidence`)이 붙어 검산 가능
- **입력 검증**: pydantic 모델(언어·통화 Literal, 수량 범위, 스캔 입력 '정확히 하나'), 이미지는 base64·크기 검증 후에만 외부 API로
- **교체 가능**: 설정·카탈로그·저장소·식별기를 `AppState`에 모아 주입. 테스트는 임시 DB + 가짜 provider로 네트워크 없이 실행
- **품질 게이트**: `ruff check .` 0건, CI에서 자동 실행

## 이전 프로젝트(장바구니 재판소)에서 옮겨 쓴 것
SQLite 사용자별 저장 구조(store.py), 이미지 AI 호출 구조(ai.py), "같은 종류 + 겹치는 속성 → 중복" 판정 아이디어, 규칙 엔진 + 근거표 방식, 흰 배경·블랙·은색 테두리 디자인.

## 하지 않은 것 → 기말까지
일본어·중국어 화면(데이터는 이미 있음, 화면 문구만 추가하면 됨) · 실사용자 평가 3명 · 실시간 제품의 본국 가격(해외 판매가 소스 연결) · 실시간 제품 성분 상세(현재는 제목 키워드 태그만) · 환율 자동 갱신 · 역직구 재구매 링크 연결 · 매장 선택(다이소·백화점) · 무료 주소 배포(Render/Vercel) · 소스 공개.

## 데이터 출처
- 실시간 상품(이름·가격·이미지·판매 링크): 네이버 쇼핑 검색 API, 판매처 이름에 "올리브영"이 들어간 상품만. 올리브영 사이트 직접 접근은 봇 차단(403)이라 쓰지 않음
- 택스리펀 규칙(최소 ₩15,000, 즉시환급 1회 ₩1,000,000 미만·총 ₩5,000,000, 구간 환급률): namanecard 2026 가이드 — 근사치, 시연 전 확인
- 환율: 실시간은 Frankfurter(ECB 기준환율, api.frankfurter.dev) · 참고값은 Banque de France 2026-11-02 EUR 기준 교차환율 (`LIVE_FX=0`이면 참고값만)
- 제품 가격: 올리브영 정가·해외 온라인 판매가 대략값 — **시연 전 실제 값으로 확인**
