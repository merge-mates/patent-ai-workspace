---
실험: m2-i2-law-bm25-char-bigram
기능: 검색 (법령, PR #117 리뷰 요청 2 후속)
담당: 은진
날짜: 2026-11-20
기준선: experiments/m2-i2-law-bm25-v2/
평가 세트: tune v2
바꾼 것: `impl`: law_bm25 → bm25 (bm25s lucene, `tokenizer: char_bigram`, `bm25.unique_query_terms: true`)
주 지표: hit@5
---
# 법령 BM25를 합친 bm25 구현으로 (확인용)

**가설**: law_bm25와 같은 셈(두 글자, 질의 낱말 한 번씩, 범위 안 통계)이면 점수가 같다. lucene 점수는 Okapi의 1/(k1+1)배라 순위는 같다.
**종류**: 구현 비교
**바꾼 것 (하나)**: `impl` law_bm25 → bm25. 설정 모양은 bm25 쪽(`settings.bm25.k1·b`)으로 옮겼고 값은 같다.

## 결과 (scores.json)
| 지표 | 기준선 (law_bm25) | 이번 (bm25) | 차이 |
|---|---|---|---|
| hit@1 / @3 / @5 / @10 | 0.632 / 0.947 / 1.000 / 1.000 | 같음 | 0 |
| recall@5 | 0.974 | 0.974 | 0 |
| 비용($) / 외부 호출 | 0 / 0 | 0 / 0 | |

- n = 19줄, 지문 `043fc719…` 같음. 11.1초 → 11.9초.

## 실패 유형 (개수)
| 유형 | 기준선 | 이번 |
|---|---|---|
| excluded_* 전부 | 0 | 0 |
| CQ 후보 | 0 | 0 |

## 해석
- 합친 구현이 law_bm25와 같은 셈을 한다는 확인 (둘 다 결정적 계산).
- `unique_query_terms: false`(bm25s 기본, 질의 낱말을 나온 만큼 셈)로 돌리면 hit@1/3/5/10 = 0.211 / 0.526 / 0.737 / 1.000. 긴 거절이유 질의에서 흔한 두 글자가 반복돼 점수를 끌고 간다. 그 scores.json은 남기지 않았다.

## 다음
- 두 말뭉치 `unique_query_terms`를 하나로 정하기 (`m2-i2-cite-search-bm25-unique-query` 참고).
