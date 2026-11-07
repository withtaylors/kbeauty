# 검증 ③ 사용자 반응

> **주의:** 영어 사용자를 구하지 못해 **AI(Claude)가 영어 사용 관광객 역할로 대신 평가**했습니다.
> 실제 사용자 평가가 아니므로 슬라이드에도 "AI 대리 평가"로 표시하고, 기말까지 실사용자 3명 평가로 바꿀 계획입니다.

## 과제 (1분)
"Pretend you're in Olive Young. Scan or search 3 products, add 2 to your list, then open Trip."

## 질문
- **Q1.** Did you understand what each product is and whether it suits your skin? (Yes, clearly / Mostly / No)
- **Q2.** If you were shopping in Korea, would you use this in the store? (Yes / Maybe / No)
- **Q3.** Which part was most useful? (Explanation / Price vs. home / Duplicate warning / Tax refund & trip summary)
- **Q4.** One thing you'd change?

## 결과

| 평가자 | 언어·통화 | Q1 | Q2 | Q3 | Q4 |
|---|---|---|---|---|---|
| AI 대리 평가 (Claude, 미국 관광객 역할, 민감성 피부) | English · USD | Yes, clearly | Yes | Price vs. home — "$13.40 vs $18.00, 26% cheaper"가 매대 앞에서 바로 결정하게 해 줌 | **담기 직후 카드에 노란 경고 "Already in your list"가 떠서 오류처럼 보였음** |
| 실사용자 1 | | | | | |
| 실사용자 2 | | | | | |

## 평가에서 나온 문제와 수정
| 발견 | 수정 | 결과 |
|---|---|---|
| 리스트에 담은 직후 같은 카드에 노란 경고 "Already in your list"가 떠서 실수한 것처럼 보임 | "이미 담음"(같은 제품)과 "비슷한 제품"(다른 제품, 성분 겹침)을 분리. 같은 제품이면 초록색 "✓ In your list" + 버튼 "Add one more" | 재검사에서 경고 대신 확인 표시로 바뀜 (화면 캡처) |

**성공 기준:** Q2에서 "Yes" 과반 → AI 대리 평가 기준 충족, 실사용자 평가는 기말까지.
