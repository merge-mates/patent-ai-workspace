---
실험: m2-i1-law-bm25-baseline
기능: 검색 (법령, 이슈 #66)
담당: 은진
날짜: 2026-11-19
기준선: 없음 (첫 기준선)
평가 세트: tune v1 (임시, 아래 "정답" 참고)
---
# 법령 BM25 기준선 (조문만)

**가설**: 기준선이라 가설 없음. OA 거절이유 본문(조문 표기 가림)만으로 그 거절이유가 짚은 조문을 BM25가 몇 위에 찾는지 잰다.
**종류**: 첫 기준선
**바꾼 것 (하나)**: 없음. `impl: law_bm25`, `settings`: `tokenizer: char_bigram`, `k1: 1.5`, `b: 0.75`

## 결과 (scores.json)
| 지표 | 기준선 | 이번 | 차이 |
|---|---|---|---|
| hit@1 | | 0.632 | |
| hit@3 | | 0.947 | |
| hit@5 | | 1.000 | |
| hit@10 | | 1.000 | |
| recall@1 / @3 / @5 | | 0.605 / 0.921 / 0.974 | |
| 무작위 hit@5 | | 0.006 | |
| 비용($) | | 0 | |
| 외부 API 호출 | | 0 | |

- n = 19줄 (tune 10건의 거절이유 19개), 색인 `law-idx-v1` 지문 `76c3abe7…` (조각 10,649개).
- DB(`PostgresChunkRepository`)와 `--chunks` 메모리 채점 점수가 같다.

## 실패 유형 (개수)
| 유형 | 기준선 | 이번 |
|---|---|---|
| excluded_edition_unverified (판본 모르는 정답 줄) | | 0 |
| excluded_no_edition_in_scope | | 0 |
| excluded_no_location / clarity / same_as_other / body_missing | | 0 |
| CQ 후보 (k=10 안에 못 찾음) | | 0 (경고 나옴) |

## 해석
- **조문만 기준선**이다. 색인에 심사기준이 없어서 심사기준 정답은 아직 없다. 심사기준을 넣은 `law-idx-v2`에서 다시 채점하고, 지문이 달라 이 점수와 바로 비교하지 않는다.
- 1위를 놓친 7줄은 대부분 명확성(제42조 제4항) 질의에서 시행령 제5조 제6항(청구범위 기재 방법)이나 제47조가 위로 온 경우다. 낱말이 비슷한 조문끼리 가려내지 못한다.
- 19줄, 조문 종류 4개(29조 1·2항, 42조 3·4·8항, 시행령 5조 6항)뿐이라 점수가 높게 나오기 쉽다. CQ 후보가 0건이라 M2에서 그래프 판단에 쓸 "못 찾은 질문"이 이 세트에선 안 나온다.

## 정답
- 원본: 드라이브 `tune_search_v0/tune_search_gold_1118_검수완료.json` (검수 11/18) → `eval.retrieval.law_gold`로 변환.
- 공용 `data/goldsets/VERSION`이 정수가 아니라(`tune-f1-v0`) 채점기가 멈춰서, worktree `data/goldsets/`에 `VERSION=1`과 `tune/retrieval/law_gold.jsonl`을 따로 두고 `--goldsets-root`로 채점했다. 공용 VERSION 형식을 정하면 다시 돌린다.

## 해 본 것 / 버린 것
- 없음 (첫 기준선)

## 다음
- 벡터(`embed()`) 채점을 같은 `law-idx-v1`에서 (다음 PR).
- 심사기준 조각을 넣은 `law-idx-v2`에서 BM25 다시 채점.
- 비교 후보: `tokenizer: whitespace` / 형태소 분석기, 질의에서 쪽 머리말·줄바꿈 잡음 빼기.
