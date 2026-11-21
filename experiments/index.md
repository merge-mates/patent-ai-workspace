<!-- eval/make_index.py가 만든다. 손으로 고치지 않는다. -->
# 실험 점수 표
| 실험 | 기능 | 바꾼 것 | 주 지표 | 기준선 대비 | 비용 | 카드 |
|---|---|---|---|---|---|---|
| m1-i3-f1-effort-low | F1 | `settings.effort`: medium → low | field_accuracy 0.568 | -0.069 | $0.00 | [card](m1-i3-f1-effort-low/card.md) |
| m1-i3-f1-effort-medium | F1 | `settings.effort`: (없음, 모델 기본 medium) → medium (#136 뒤 명시. 보내는 요청은 기준선과 같음) | field_accuracy 0.637 | +0.031 | $0.00 | [card](m1-i3-f1-effort-medium/card.md) |
| m1-i3-f1-model-input-tables | F1 | `settings.model_input`: raw → tables_md | tables_md.confirmed 94.000 | 기준선 | $0.03 | [card](m1-i3-f1-model-input-tables/card.md) |
| m1-i3-f1-pdf-tool | F1 | PDF 도구 4개 비교 (pdfplumber 유지 결정의 기준선) | pdfplumber.task2_with_cells 1.000 | 기준선 | - | [card](m1-i3-f1-pdf-tool/card.md) |
| m1-i3-f1-read-oa-baseline | F1 | 기준선 (처음 정답 대비 채점, 바꾼 것 없음) | field_accuracy 0.605 | 기준선 | $0.00 | [card](m1-i3-f1-read-oa-baseline/card.md) |
| m2-i1-cite-search-bm25-baseline | cite-search | 기준선 (처음 측정, 바꾼 것 없음) | hit@5 0.500 | - | $0.00 | [card](m2-i1-cite-search-bm25-baseline/card.md) |
| m2-i1-law-bm25-baseline | 검색 (법령, 이슈 #66) | 기준선 (처음 측정, 바꾼 것 없음) | hit@5 1.000 | - | $0.00 | [card](m2-i1-law-bm25-baseline/card.md) |
| m2-i2-cite-search-bm25-unique-query | 검색 (인용문헌, PR #117 리뷰 요청 2 후속) | `settings.bm25.unique_query_terms`: false → true | hit@5 0.412 | -0.088 | $0.00 | [card](m2-i2-cite-search-bm25-unique-query/card.md) |
| m2-i2-cite-search-bm25-v2 | cite-search (이슈 #67) | `index_version` cite-idx-v1 → cite-idx-v2 (조각 글·위치는 같고 `embedding`과 판 앞말만 다름). 검색 설정은 그대로 | hit@5 0.500 | - | $0.00 | [card](m2-i2-cite-search-bm25-v2/card.md) |
| m2-i2-cite-search-hybrid-rrf | cite-search (이슈 #67) | `mode`·`impl`: bm25 → hybrid (BM25 + 벡터를 RRF로 섞음, `rrf_k`=60, 가중치 bm25 0.5 / vector 0.5) | hit@5 0.574 | +0.074 | $0.00 | [card](m2-i2-cite-search-hybrid-rrf/card.md) |
| m2-i2-cite-search-vector | cite-search (이슈 #67) | `mode`·`impl`: bm25 → vector (`cite-idx-v2` = v1 조각 + text-embedding-3-small 벡터, 1536차원) | hit@5 0.559 | +0.059 | $0.00 | [card](m2-i2-cite-search-vector/card.md) |
| m2-i2-law-bm25-char-bigram | 검색 (법령, PR #117 리뷰 요청 2 후속) | `impl`: law_bm25 → bm25 (bm25s lucene, `tokenizer: char_bigram`, `bm25.unique_query_terms: true`) | hit@5 1.000 | +0.000 | $0.00 | [card](m2-i2-law-bm25-char-bigram/card.md) |
| m2-i2-law-bm25-char-bigram-count-repeats | 검색 (법령, PR #186 리뷰 참고 후속) | `settings.bm25.unique_query_terms`: true → false | hit@5 0.737 | -0.263 | $0.00 | [card](m2-i2-law-bm25-char-bigram-count-repeats/card.md) |
| m2-i2-law-bm25-kiwi | 검색 (법령, PR #117 리뷰 요청 2 후속) | `settings.tokenizer`: char_bigram → kiwi (pos_tags는 인용문헌 기준선과 같음) | hit@5 1.000 | +0.000 | $0.00 | [card](m2-i2-law-bm25-kiwi/card.md) |
| m2-i2-law-bm25-v2 | 검색 (법령, 이슈 #66) | `index_version`: law-idx-v1 → law-idx-v2 (조각 같음, embedding만 더함) | hit@5 1.000 | +0.000 | $0.00 | [card](m2-i2-law-bm25-v2/card.md) |
| m2-i2-law-vector-baseline | 검색 (법령, 이슈 #66) | `mode`·`impl`: bm25·law_bm25 → vector·vector (`law-idx-v2` = v1 조각 + text-embedding-3-small 벡터) | hit@5 0.316 | -0.684 | $0.00 | [card](m2-i2-law-vector-baseline/card.md) |
