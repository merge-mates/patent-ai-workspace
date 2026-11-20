<!-- eval/make_index.py가 만든다. 손으로 고치지 않는다. -->
# 실험 점수 표
| 실험 | 기능 | 바꾼 것 | 주 지표 | 기준선 대비 | 비용 | 카드 |
|---|---|---|---|---|---|---|
| m1-i3-f1-effort-low | F1 | `settings.effort`: medium → low | field_accuracy 0.568 | -0.069 | $0.00 | [card](m1-i3-f1-effort-low/card.md) |
| m1-i3-f1-effort-medium | F1 | `settings.effort`: (없음, 모델 기본 medium) → medium (#136 뒤 명시. 보내는 요청은 기준선과 같음) | field_accuracy 0.637 | +0.031 | $0.00 | [card](m1-i3-f1-effort-medium/card.md) |
| m1-i3-f1-model-input-tables | F1 | `settings.model_input`: raw → tables_md | tables_md.confirmed 94.000 | 기준선 | $0.03 | [card](m1-i3-f1-model-input-tables/card.md) |
| m1-i3-f1-pdf-tool | F1 | PDF 도구 4개 비교 (pdfplumber 유지 결정의 기준선) | pdfplumber.task2_with_cells 1.000 | 기준선 | - | [card](m1-i3-f1-pdf-tool/card.md) |
| m1-i3-f1-read-oa-baseline | F1 | 기준선 (처음 정답 대비 채점, 바꾼 것 없음) | field_accuracy 0.605 | 기준선 | $0.00 | [card](m1-i3-f1-read-oa-baseline/card.md) |
| m1-i3-f1-read-oa-prompt-hint | F1 | `prompts/f1/read_oa.md` 14·33·59번 줄 (힌트 칸이 없으면 null, raw_text는 칸 제목 빼고 본문만) | field_accuracy 0.441 | -0.196 | $0.00 | [card](m1-i3-f1-read-oa-prompt-hint/card.md) |
| m1-i3-f1-stream-64k | F1 | 전송층 스트리밍 + `settings.max_tokens`: 16000 → 64000 | field_accuracy 0.600 | +0.159 | $0.00 | [card](m1-i3-f1-stream-64k/card.md) |
| m2-i1-cite-search-bm25-baseline | cite-search | 기준선 (처음 측정, 바꾼 것 없음) | hit@5 0.500 | - | $0.00 | [card](m2-i1-cite-search-bm25-baseline/card.md) |
| m2-i1-law-bm25-baseline | 검색 (법령, 이슈 #66) | 기준선 (처음 측정, 바꾼 것 없음) | hit@5 1.000 | - | $0.00 | [card](m2-i1-law-bm25-baseline/card.md) |
| m2-i2-law-bm25-v2 | 검색 (법령, 이슈 #66) | `index_version`: law-idx-v1 → law-idx-v2 (조각 같음, embedding만 더함) | hit@5 1.000 | +0.000 | $0.00 | [card](m2-i2-law-bm25-v2/card.md) |
| m2-i2-law-vector-baseline | 검색 (법령, 이슈 #66) | `mode`·`impl`: bm25·law_bm25 → vector·vector (`law-idx-v2` = v1 조각 + text-embedding-3-small 벡터) | hit@5 0.316 | -0.684 | $0.00 | [card](m2-i2-law-vector-baseline/card.md) |
