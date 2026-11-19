<!-- eval/make_index.py가 만든다. 손으로 고치지 않는다. -->
# 실험 점수 표
| 실험 | 기능 | 바꾼 것 | 주 지표 | 기준선 대비 | 비용 | 카드 |
|---|---|---|---|---|---|---|
| m2-i1-cite-search-bm25-baseline | cite-search | 기준선 (처음 측정, 바꾼 것 없음) | hit@5 0.500 | - | $0.00 | [card](m2-i1-cite-search-bm25-baseline/card.md) |
| m2-i1-law-bm25-baseline | 검색 (법령, 이슈 #66) | 기준선 (처음 측정, 바꾼 것 없음) | hit@5 1.000 | - | $0.00 | [card](m2-i1-law-bm25-baseline/card.md) |
| m2-i2-law-bm25-v2 | 검색 (법령, 이슈 #66) | `index_version`: law-idx-v1 → law-idx-v2 (조각 같음, embedding만 더함) | hit@5 1.000 | +0.000 | $0.00 | [card](m2-i2-law-bm25-v2/card.md) |
| m2-i2-law-vector-baseline | 검색 (법령, 이슈 #66) | `mode`·`impl`: bm25·law_bm25 → vector·vector (`law-idx-v2` = v1 조각 + text-embedding-3-small 벡터) | hit@5 0.316 | -0.684 | $0.00 | [card](m2-i2-law-vector-baseline/card.md) |
