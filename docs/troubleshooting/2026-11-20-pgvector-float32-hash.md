---
날짜: 2026-11-20
겪은 사람: 재아 (리뷰 에이전트가 찾음)
관련: 이슈 #67, PR #163, `src/patent_ai/retrieval/law_index_db.py`, 법령 `law-idx-v2`(#66)에도 해당
---
# 같은 벡터 색인 판을 DB에 다시 넣으면 "내용이 다르다, 새 판으로"로 멈춘다

**증상**: `python -m patent_ai.retrieval.law_index_db --jsonl <v2 JSONL> --index-version <판>`을 그 판이 이미 DB에 있는 채로 다시 돌리면, 같은 JSONL인데도 "같은 판·다른 내용" 오류가 나고 새 판(v<N+1>)을 만들라고 한다. 벡터가 없는 v1 판에서는 안 생긴다.
**원인**: 넣기 전 검사가 JSONL 조각과 DB에서 다시 읽은 조각의 내용 해시(`content_sha256`)를 비교한다. JSONL 벡터는 float64인데 pgvector `vector` 컬럼은 float32(4바이트)로 저장한다 (pgvector README, 오픈소스). 다시 읽은 값이 반올림돼 해시가 달라진다. 테스트 벡터가 `[0.1] * 1536`이었는데 0.1은 float32로 갔다 와도 0.1이 돼서 테스트가 못 잡았다.
**해결**: 해시하기 전에 벡터를 float32로 맞춘다 (`struct.pack("<f")` 왕복, `law_index_db._as_float32`). DB에 판 지문을 따로 저장하지 않고 넣을 때마다 다시 계산하므로 기존 판과 어긋나지 않는다.
**다시 안 생기게**: db 테스트 벡터는 float32 왕복에서 바뀌는 값(`0.0123456789123`)을 쓰고, 첫 넣기와 둘째 넣기 사이에 `session.expire_all()`로 DB에서 다시 읽는다 (`tests/test_cite_index_db.py::test_v2를_두_번_넣어도_줄_수가_같고_벡터가_저장된다`). 다른 표에 벡터를 넣고 비교하는 코드도 같은 정밀도로 맞춘 뒤 비교한다.
