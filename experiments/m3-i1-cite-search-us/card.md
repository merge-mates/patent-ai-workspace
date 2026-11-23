---
실험: m3-i1-cite-search-us
기능: cite-search (이슈 #308)
담당: 재아
날짜: 2026-11-23
기준선: experiments/m3-i1-cite-search-us/
평가 세트: tune v3 대기 (지금 tune v2의 cite_gold.jsonl·cite_doc_ids.yaml에 미국 줄 0개)
바꾼 것: 기준선 (미국 공보를 색인에 넣은 cite-idx-us1에서 미국 줄 첫 점수, BM25·벡터·하이브리드 RRF 세 방식)
주 지표: hit@10
---
# 인용문헌 미국 공보 검색 첫 점수 (이슈 #308 task 4)

**판 3 미국 7줄 대기.** 11/23 지금 tune 정답(`data/goldsets/tune/retrieval/cite_gold.jsonl`, `cite_doc_ids.yaml`)에 미국 문헌 줄이 0개라 채점하지 않았다. 그래서 scores.json이 없다. 정답 파일은 고치지 않았다.

**가설**: 없음 (기준선). 한국어 청구항 질의로 영어 조각을 번역 없이 찾을 때, BM25는 겹치는 낱말이 영문 약어·숫자뿐이라 0에 가깝고 벡터(text-embedding-3-small, 다국어)가 대부분을 맞힌다고 짐작한다. BM25가 0에 가까우면 그때 질의 영어 번역 BM25를 변형으로 비교한다 (이슈 #308 "고려했지만 쓰지 않은 것" 2번).
**종류**: 기준선 (세 방식 비교)

## 판 3이 들어온 뒤 돌릴 명령
하이브리드 (이 config 그대로):
`uv run python eval/run_eval.py --config experiments/m3-i1-cite-search-us/config.yaml --chunks data/processed/cite_search/cite-idx-us1.jsonl`

- 먼저 질의 벡터 (유료, 질의 수백 개라 몇 센트 아래): `uv run --env-file .env python -m eval.retrieval.embed_queries --config config/index/cite-idx-us1.yaml --gold data/goldsets/tune/retrieval/cite_gold.jsonl --out work/retrieval/m3-i1-cite-search-us/query_vectors.json`
- BM25·벡터: config의 `mode`·`impl` 두 줄을 `bm25`/`bm25`, `vector`/`vector`로 바꿔 같은 명령. 세 번 모두 `--rows-out work/retrieval/m3-i1-cite-search-us/<방식>.rows.jsonl`을 붙인다.
- 미국 줄만 Hit@10: `uv run python -m eval.retrieval.compare --rows bm25=<…> vector=<…> hybrid=<…> --k 10` 표의 `미국 공보` 묶음 (doc_id가 `US`로 시작하는 줄, #308에서 더함). 한국 공보·논문 묶음은 cite-idx-v4 점수와 지문이 달라 직접 비교하지 않는다.

## 색인 (cite-idx-us1)
- 조각: `config/cite_search.yaml` 청킹 (한국 v1 규칙 그대로 + 미국 `us_chunking`·`us_columns`·`us_granted`), 문헌은 `data/raw/cited_v2` PDF 전부 (미국 공보 50: 공개공보 46, 등록공보 4). 만드는 법은 `config/index/cite-idx-us1.yaml` 머리 주석.
- 미국 공개공보 46건: 요약 46, 문단 5073, 청구항 955 조각. 문단 번호 빠짐 284개 (글자층에 번호 자체가 없는 OCR 빠짐, 조각 글자는 앞 문단에 남음), 순서 어긋남 무시 100개.
- 미국 등록공보 4건: 칼럼:줄 조각 352 (15줄 창), 요약 4. 칼럼 번호 불일치 0.
- 위 둘은 색인 전체 숫자다. 청킹 규칙은 tune 미국 7건(공개 6, 등록 1)으로만 다시 검사했다 (PR #320 고침): 공개 6건 문단 467·빠짐 19·역순 28, 등록 1건 칼럼:줄 102·불일치 0·맞춤 오차 최대 0.022줄. #229 tune 미국 17건을 받은 뒤 다시 검사한다.
- 11/23 만듦 (`data/processed/cite_search/cite-idx-us1.jsonl`, git 밖): 문헌 254 (건너뜀 19), 조각 31798 (요약 253, 도면 설명 1802, 청구항 3873, 본문 25870), 그중 미국 6430. 임베딩한 글 30643개, text-embedding-3-small 호출 307번, 입력 토큰 4,658,190, 비용 $0.0932 (`core/index_embed` 호출 기록). 모든 조각에 1536차원 벡터.

## 결과
점수 없음 (판 3 대기).

- 확인용 (11/23, scores.json 아님): 이 색인을 `--chunks`로 지금 tune v2 정답 68줄(한국·논문)에 하이브리드로 채점하면 Hit@1·3·5·10 = 0.162 / 0.412 / 0.574 / 0.706. `m2-i2-cite-search-hybrid-rrf`(cite-idx-v2)와 같다. 미국 공보를 더해도 한국·논문 검색은 그대로이고, us1이 채점 경로에서 읽힌다. 질의 벡터는 그 실험의 기록 파일이라 비용 $0.

## 다음
- 판 3이 들어오면 위 명령으로 세 방식 표를 채우고 BM25가 0에 가까운지 본다.
- 칼럼 짚음 1줄: F3 `examiner.py`는 칼럼:줄을 label 글자가 같을 때만 맞음으로 봐서 15줄 창과 거의 안 맞는다 (채점기 `CiteMatcher`는 정렬 키 겹침이라 영향 없음). 후속 이슈 후보.
