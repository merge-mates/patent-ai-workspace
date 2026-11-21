---
실험: m2-i2-cite-search-bm25-v2
기능: cite-search (이슈 #67)
담당: 재아
날짜: 2026-11-20
기준선: experiments/m2-i1-cite-search-bm25-baseline/ (판이 달라 점수가 같은지만 봄)
평가 세트: tune v2
바꾼 것: `index_version` cite-idx-v1 → cite-idx-v2 (조각 글·위치는 같고 `embedding`과 판 앞말만 다름). 검색 설정은 그대로
주 지표: hit@5
---
# 인용문헌 BM25, cite-idx-v2로 다시 채점

**가설**: 판 앞말과 벡터 칸만 다르므로 BM25 점수는 v1과 같다. 같으면 벡터·하이브리드를 같은 지문에서 이 점수와 비교한다.
**종류**: 기준선 다시 재기 (채점기 규칙 "지문이 다르면 비교하지 않음", design 7-5)
**바꾼 것 (하나)**: 색인 판

## 결과 (scores.json, 11/20, n=68)
| 지표 | v1 기준선 (m2-i1) | 이번 (v2) | 같음 |
|---|---|---|---|
| Hit@1 | 0.118 | 0.118 | 예 |
| Hit@3 | 0.324 | 0.324 | 예 |
| Hit@5 | 0.500 | 0.500 | 예 |
| Hit@10 | 0.618 | 0.618 | 예 |
| Recall@10 | 0.465 | 0.465 | 예 |
| 비용($) / 외부 API 호출 | 0 / 0 | 0 / 0 | |

- `gold_sha256`·`n`·뺀 줄 수(same_as_other 33, no_location 3, 범위 밖 정답 항목 10, 줄 1)·CQ 26 모두 v1과 같다.
- 지문: 조각 1998개 (v1과 같은 수). `chunk_ids_sha256`은 판 앞말이 달라 v1과 다르다 (예상대로).

## 실패 유형 (개수)
| 유형 | v1 | v2 |
|---|---|---|
| CQ (상위 10에 정답 위치 없음) | 26 | 26 |

## 해석
- v1 = v2라 아래 두 실험의 기준선으로 쓴다.

## 정답·다시 돌리기
- `tune/retrieval/cite_gold.jsonl` (공용 `data/goldsets/VERSION` = 2)
- DB 없이: `uv run python -m eval.retrieval.score --config experiments/m2-i2-cite-search-bm25-v2/config.yaml --chunks data/processed/cite_search/cite-idx-v2.jsonl`

## 다음
- 벡터·하이브리드 비교는 [m2-i2-cite-search-hybrid-rrf](../m2-i2-cite-search-hybrid-rrf/card.md) 카드.
