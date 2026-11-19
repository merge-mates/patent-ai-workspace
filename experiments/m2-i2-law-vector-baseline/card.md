---
실험: m2-i2-law-vector-baseline
기능: 검색 (법령, 이슈 #66)
담당: 은진
날짜: 2026-11-19
기준선: experiments/m2-i1-law-bm25-baseline/
평가 세트: tune v2
바꾼 것: `mode`·`impl`: bm25·law_bm25 → vector·vector (`law-idx-v2` = v1 조각 + text-embedding-3-small 벡터)
주 지표: hit@5
---
# 법령 벡터 기준선 (조문만)

**가설**: 기준선이라 가설 없음. 같은 조각·같은 질의에서 벡터 검색이 BM25와 견줘 어디까지 찾는지 잰다.
**종류**: 구현 비교 (같은 인터페이스, 검색 방식만 다름)
**바꾼 것 (하나)**: 검색 방식 `bm25` → `vector`. 조각은 v1과 같고(`law-idx-v2`에서 BM25를 다시 돌려 v1과 점수가 같음을 확인) 벡터만 더했다.

## 결과 (scores.json)
| 지표 | 기준선 (BM25) | 이번 (벡터) | 차이 |
|---|---|---|---|
| hit@1 | 0.632 | 0.158 | −0.474 |
| hit@3 | 0.947 | 0.263 | −0.684 |
| hit@5 | 1.000 | 0.316 | −0.684 |
| hit@10 | 1.000 | 0.737 | −0.263 |
| recall@5 | 0.974 | 0.289 | −0.685 |
| 비용($) | 0 | 0.0046 (조각 임베딩 0.0040 + 질의 0.0006, 한 번) | |
| 외부 API 호출 | 0 | 13 (조각 12 + 질의 1, 두 번째부터 캐시) | |

- n = 19줄. 색인 `law-idx-v2` 지문 `043fc719…` (조각 10,649개, 고유 글 1,142개만 임베딩).
- DB(`PostgresChunkRepository`)와 `--chunks` 메모리 채점 점수가 같다.

## 실패 유형 (개수)
| 유형 | 기준선 | 이번 |
|---|---|---|
| excluded_edition_unverified | 0 | 0 |
| excluded_no_edition_in_scope / no_location / body_missing | 0 | 0 |
| CQ 후보 (k=10 안에 못 찾음) | 0 | 5 |

## 해석
- 벡터가 BM25보다 크게 낮다. 질의가 OA 거절이유 전체(길면 6천 자)라 인용발명 대비 같은 잡음이 벡터 하나에 섞이고, 조문 조각은 짧고 법률 용어가 그대로 겹쳐 BM25가 유리하다.
- 검색기 버그는 아니라고 본다: 짧은 질의("통상의 기술자가 쉽게 발명할 수 있어 진보성이 없다")로는 29조 2항이 3위, 명확성 질의는 시행령 5조가 1~3위로 나온다.
- CQ 후보 5건이 처음 생겼다 (벡터로 못 찾은 질문). 11/24 그래프 판단 자료로 쓰되, BM25로는 다 찾는 질문이라 "그래프가 필요하다"의 근거로는 약하다.
- 조문만 기준선이다. 심사기준은 `law-idx-v3`에서.

## 정답
- `tune/retrieval/law_gold.jsonl` (공용 `data/goldsets/VERSION` = 2), BM25 기준선과 같은 파일.
- 질의 벡터: `uv run --env-file <.env> python -m patent_ai.core.index_embed queries --config config/index/law-idx-v2.yaml --gold <goldsets_root>/tune/retrieval/law_gold.jsonl --out work/retrieval/m2-i2-law-vector-baseline/query_vectors.json` (git 밖)
- 다시 돌리기 (DB 없이): `uv run python -m eval.retrieval.score --config experiments/m2-i2-law-vector-baseline/config.yaml --chunks data/processed/law/law-idx-v2.jsonl`

## 해 본 것 / 버린 것
- 없음 (첫 벡터 기준선)

## 다음
- 질의를 줄여 보기: 거절이유 첫 문단(결론 문장)만, 또는 인용발명 대비 표를 뺀 글.
- 다른 임베딩 모델(3-large, 한국어 모델) 비교는 설정 `config/law_search.yaml`의 model만 바꿔 새 판으로.
- BM25·벡터를 섞는 hybrid는 계약 자리만 있음 (#66 범위 밖).
