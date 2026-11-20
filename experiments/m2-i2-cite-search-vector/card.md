---
실험: m2-i2-cite-search-vector
기능: cite-search (이슈 #67)
담당: 재아
날짜: 2026-11-20
기준선: experiments/m2-i2-cite-search-bm25-v2/
평가 세트: tune v2
바꾼 것: `mode`·`impl`: bm25 → vector (`cite-idx-v2` = v1 조각 + text-embedding-3-small 벡터, 1536차원)
주 지표: hit@5
---
# 인용문헌 벡터 기준선

**가설**: 청구항과 인용문헌 문단은 같은 내용을 다른 낱말로 쓰는 일이 많아, 벡터가 BM25보다 정답 문단을 더 자주 상위 k에 올린다.
**종류**: 구현 비교 (같은 인터페이스, 검색 방식만 다름)
**바꾼 것 (하나)**: 검색 방식 `bm25` → `vector`. 같은 색인 `cite-idx-v2`(같은 지문), 같은 정답 파일.

## 결과 (scores.json, 11/20, n=68)
| 지표 | 무작위 | 기준선 (BM25, v2) | 이번 (벡터) | 차이 |
|---|---|---|---|---|
| Hit@1 | 0.075 | 0.118 | 0.147 | +0.029 |
| Hit@3 | 0.180 | 0.324 | 0.397 | +0.074 |
| Hit@5 | 0.255 | 0.500 | 0.559 | +0.059 |
| Hit@10 | 0.384 | 0.618 | 0.691 | +0.074 |
| Recall@10 | | 0.465 | 0.483 | +0.018 |
| 비용($) | | 0 | 0.0070 (조각 0.0068 + 질의 0.0002, 한 번. 채점기 밖에서 써서 scores.json·index.md에는 0) | |
| 외부 API 호출 | | 0 | 21 (조각 20 + 질의 1) | |

- 조각 1998개 중 고유 글 1908개만 임베딩 (입력 토큰 341,991). 질의 74개 (입력 토큰 12,328). 숫자는 `index_embed`·`embed_queries` 호출 기록(`call_report`)에서.
- DB(`cite_chunks`)와 `--chunks` 메모리 채점 점수가 같다.

## 실패 유형 (개수)
| 유형 | 기준선 | 이번 |
|---|---|---|
| CQ (상위 10에 정답 위치 없음) | 26 | 21 (한국 공보 21) |
| BM25에서 CQ였다가 벗어남 / 새로 CQ | | 11 / 6 |

## 해석 (사람이 고칠 것)
- 방향은 BM25보다 위지만 차이를 말할 수 없다: 상위 10에서 갈린 줄이 벡터만 11 대 BM25만 6, 부호 검정 p≈0.33, 줄 부트스트랩 95% 구간 −0.044~+0.191 (experiment-analyst 계산, 판단). 68줄은 출원 8건·문헌 16개에서 나와 독립이 아니라 이 값도 낙관적이다.
- 순위 이동은 좋아짐 26 / 나빠짐 23 / 같음 19로 거의 반반. BM25와 벡터가 서로 다른 줄을 맞힌다 → 하이브리드 근거.
- 법령(#66)에선 벡터가 BM25보다 크게 낮았는데 인용문헌에선 반대다 (법령 질의는 거절이유 전문, 인용문헌 질의는 청구항 전문이라 질의가 다름, 판단).

## 정답·다시 돌리기
- `tune/retrieval/cite_gold.jsonl` (VERSION 2), BM25와 같은 파일
- 질의 벡터: `uv run --env-file <.env> python -m eval.retrieval.embed_queries --config config/index/cite-idx-v2.yaml --gold <goldsets_root>/tune/retrieval/cite_gold.jsonl --out work/retrieval/m2-i2-cite-search-vector/query_vectors.json` (git 밖)
- DB 없이: `uv run python -m eval.retrieval.score --config experiments/m2-i2-cite-search-vector/config.yaml --chunks data/processed/cite_search/cite-idx-v2.jsonl`

## 다음
- 세 방식 비교와 다음 실험은 [m2-i2-cite-search-hybrid-rrf](../m2-i2-cite-search-hybrid-rrf/card.md) 카드.
