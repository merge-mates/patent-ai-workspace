<!-- eval/make_index.py가 만든다. 손으로 고치지 않는다. -->
# 실험 점수 표
| 실험 | 기능 | 바꾼 것 | 주 지표 | 기준선 대비 | 비용 | 카드 |
|---|---|---|---|---|---|---|
| m1-i3-f1-effort-low | F1 | `settings.effort`: medium → low | field_accuracy 0.568 | -0.069 | $0.00 | [card](m1-i3-f1-effort-low/card.md) |
| m1-i3-f1-effort-low-stream64k | F1 | `settings.effort`: medium → low (스트리밍·max_tokens 64000 판에서) | field_accuracy 0.653 | +0.067 | $0.00 | [card](m1-i3-f1-effort-low-stream64k/card.md) |
| m1-i3-f1-effort-medium | F1 | `settings.effort`: (없음, 모델 기본 medium) → medium (#136 뒤 명시. 보내는 요청은 기준선과 같음) | field_accuracy 0.637 | +0.031 | $0.00 | [card](m1-i3-f1-effort-medium/card.md) |
| m1-i3-f1-model-input-tables | F1 | `settings.model_input`: raw → tables_md | tables_md.confirmed 94.000 | 기준선 | $0.03 | [card](m1-i3-f1-model-input-tables/card.md) |
| m1-i3-f1-pdf-tool | F1 | PDF 도구 4개 비교 (pdfplumber 유지 결정의 기준선) | pdfplumber.task2_with_cells 1.000 | 기준선 | - | [card](m1-i3-f1-pdf-tool/card.md) |
| m1-i3-f1-prompt-null-wording | F1 | `prompts/f1/read_oa.md` null·문자열 예외 문구 맞추기 (이슈 #193 task 1, sha256 앞 12자 d680efd54818 → a2d095469fda, 커밋 9d99d3b) | field_accuracy 0.674 | +0.088 | $0.00 | [card](m1-i3-f1-prompt-null-wording/card.md) |
| m1-i3-f1-read-oa-baseline | F1 | 기준선 (처음 정답 대비 채점, 바꾼 것 없음) | field_accuracy 0.605 | 기준선 | $0.00 | [card](m1-i3-f1-read-oa-baseline/card.md) |
| m1-i3-f1-read-oa-prompt-hint | F1 | `prompts/f1/read_oa.md` 14·33·59번 줄 (힌트 칸이 없으면 null, raw_text는 칸 제목 빼고 본문만) | field_accuracy 0.441 | -0.196 | $0.00 | [card](m1-i3-f1-read-oa-prompt-hint/card.md) |
| m1-i3-f1-read-oa-prompt-shape | F1 | `prompts/f1/read_oa.md`에 모양 규칙 3줄 (no_location은 객체, clarity_reason만 문자열, JSON 객체 하나로 끝냄·없는 키 금지) | field_accuracy 0.586 | -0.014 | $0.00 | [card](m1-i3-f1-read-oa-prompt-shape/card.md) |
| m1-i3-f1-stream-64k | F1 | 전송층 스트리밍 + `settings.max_tokens`: 16000 → 64000 | field_accuracy 0.600 | +0.159 | $0.00 | [card](m1-i3-f1-stream-64k/card.md) |
| m2-f3-skeleton | F3 | 기준선 (F3 뼈대 첫 tune 실행, 바꾼 것 없음) | search_recall 0.584 | 기준선 | $0.00 | [card](m2-f3-skeleton/card.md) |
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
| m2-i3-cite-search-bm25-noise-b | cite-search (이슈 #178 둘째 점수) | `noise_scope`: 없음(그 인용문헌 안) → `retrieval/cite_noise_b.jsonl` (B안: tune 인용문헌 전체 풀). 검색 설정·색인은 그대로 | hit@10 0.353 | -0.265 | $0.00 | [card](m2-i3-cite-search-bm25-noise-b/card.md) |
| m2-i3-cite-search-bm25-noise-c | cite-search (이슈 #178 둘째 점수, C안) | 색인 `cite-idx-v1` → `cite-idx-v4`(C안 공보 115·tune 30건 인용 공보 더함), `noise_scope`: B(옛 tune 인용 16건 풀) → B(tune 30건 인용 풀) + C(OA마다 같은 IPC·비슷한 낱말 한국 공보, 그 OA 줄에만) | hit@10 0.265 | -0.088 | $0.00 | [card](m2-i3-cite-search-bm25-noise-c/card.md) |
| m2-i3-cite-search-hybrid-noise-c | cite-search (이슈 #178 둘째 점수, C안) | `mode`·`impl`: bm25 → hybrid (같은 색인 cite-idx-v4·같은 C안 범위) | hit@10 0.338 | +0.074 | $0.00 | [card](m2-i3-cite-search-hybrid-noise-c/card.md) |
| m2-i3-cite-search-vector-noise-c | cite-search (이슈 #178 둘째 점수, C안) | `mode`·`impl`: bm25 → vector (같은 색인 cite-idx-v4·같은 C안 범위) | hit@10 0.338 | +0.074 | $0.00 | [card](m2-i3-cite-search-vector-noise-c/card.md) |
| m3-f4-skeleton | F4 | 기준선 (F4 뼈대 첫 tune 실행, 바꾼 것 없음) | 점수 없음 | - | - | [card](m3-f4-skeleton/card.md) |
