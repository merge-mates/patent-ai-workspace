---
출처: Google Patents 문헌 페이지의 공보 PDF (특허) · KIPRIS 공개전문 (한국 공개공보 2개) · 논문 공개 판 PDF (논문 3건)
받은 날: 2026-11-18, 2026-11-21 (#168)
담당: 재아 (카드), 은진 (수집)
---
# 인용문헌 원문 (tune) 데이터 카드

## 1. 출처와 이용 조건
- 어디서:
  - 특허 공보: Google Patents 문헌 페이지에서 PDF 주소(`patentimages.storage.googleapis.com`)를 브라우저로 찾고 그 PDF를 바로 받음 (11/18, 은진 님. 페이지 자체는 스크립트 접근을 막음).
  - 논문 1건: 학회 공개 판 PDF (CVF Open Access, `openaccess.thecvf.com`). 제목은 tune 내용이라 적지 않는다. arXiv 판도 받았지만 OA가 학회판 쪽·줄로 짚어 학회판만 쓴다.
- 라이선스·이용 조건:
  - 특허 공보: 특허청이 공개한 공문서.
  - 논문: 저작권은 출판사에 있다. 내부 평가에만 쓰고 git·공개 배포에 넣지 않는다.
  - 둘 다 원문은 git·공개 배포에 넣지 않는다 (architecture.md "외부 모델로 보내는 자료" 표).
- 위치: `data/raw/cited_v2/<출원번호>/<공보번호>.pdf` (git 제외). 출원번호 = 그 인용문헌을 쓴 OA의 사건

## 2. 무엇이 들었나
| 필드 | 타입 | 뜻 | 예 (모양만) |
|---|---|---|---|
| 폴더 이름 | 문자열 | 인용한 사건의 출원번호 | `10201XXXXXXXX` |
| 파일 이름 | 문자열 | 공보 번호 = `doc_id` (f1-oa-gold.md 2.3 키 꼴) | `KR2011XXXXXXXA`, `KR10XXXXXXXB1` |
| 본문 | PDF 글자층 | 공보 전문 (서지, 요약, 청구범위, 발명의 설명 식별번호, 도면) | |

- 새 저장소 `data/raw/cited_v2/`에는 **tune 사건 것만** 있다 (11/21 셈 24건, 아래 크기 줄). report·spare 사건의 인용문헌은 옮기지 않았다.
  - 팀 공유 사본: tune은 드라이브 `02_인용문헌/tune_1118/cited_v2/`, report·spare를 포함한 전체는 `01_OA_사건자료_v2/인용문헌_원문_v2_전체_1118/cited_v2/` (봉인, report 채점 전에는 열지 않음).
  - 은진 로컬 옛 폴더(`~/dev/Patent_AI_Workspace/data/raw/cited_v2/`, 은진 맥에만 있음)에도 같은 전체가 있고, 받기 스크립트·기록(`fetch_cited.py`, `log_*.json`)은 그 `_meta/`에만 있다.
  - report 채점 때 이 자료를 어디서 읽을지는 아직 설정·코드에 없다 (`config/cite_search.yaml`은 `data/raw/cited_v2`만 읽음). report 채점 전에 따로 정한다.
- 크기 (11/21 셈, tune 30건 중 인용문헌이 있는 24건): PDF 58개, 111MB. 한국 공보 47개(공개 A 36, 등록 B1 11), 미국 공보 7개, 논문 3건 4파일(1건은 두 판). 그 밖 나라 없음. 인용문헌이 없는 6건은 거절이유가 명확성뿐이다.
  - 11/19 셈(tune 10건 때): 사건 8건, PDF 17개, 51MB. 한국 공보 15개(공개 A 9, 등록 B1 6), 논문 1건 2판.
- 11/21 [#168](https://github.com/merge-mates/patent-ai-workspace/issues/168) tune 30건 늘리기: 더한 20건 중 인용문헌이 있는 16건(G2 4건은 명확성만이라 인용 없음)의 것을 받았다.
  - 받음 41개: Google Patents 공보 PDF(같은 방법, 1초 간격, `%PDF` 확인) 한국 공보 32개(공개 A 27, 등록 B1 5)·미국 공보 7개 중, Google에 PDF가 없던 한국 공개공보 2개는 KIPRIS 공개전문으로 받았고, 미국 1개는 나중에 같은 Google Patents 방법으로 받았다. 공개 논문 2건(학술지 1, 학회 1)은 학술지 공개 판과 대학 강의 자료실의 학회 판 PDF로 받았다.
  - 못 받음 (남은 일): 논문 2건(국내 학술지 1, 기관 보고서 1). 받을 곳을 못 찾았다.
  - 안 쓰는 2개: 대기열에서 빠진 사건(의견서 뷰어가 빈 화면) 폴더의 한국 공보 2개. 색인기가 `cited_v2/` 아래 `_meta` 밖 PDF를 다 읽으므로(`cite_index/__main__.py` `_list_pdfs`) `cited_v2/_meta/unused_t168/`로 옮겼다. 드라이브 `02_인용문헌/tune_1118/cited_v2/`에는 처음부터 안 올렸다 (16폴더 41개).
  - 색인: 11/22 `cite-idx-v4`(#178)에 한국 공보 47개와 논문 1건(학회판)이 들어갔다. 미국 공보 7개는 청킹이 아직 없어 빠진다 (#25 댓글: 2개는 스캔본이라 OCR 필요, 5개는 문단 번호가 글자층에서 거의 안 잡힘).
- 11/22 [#178](https://github.com/merge-mates/patent-ai-workspace/issues/178) C안 노이즈 공보 115개 (인용문헌이 아니다): `data/raw/cited_v2/noise_c/<doc_id>.pdf`, 115MB (공개 A 82, 등록 B1 33). OA 24통마다 같은 IPC·청구항 낱말로 KIPRIS Plus 공보 검색(`scripts/fetch_noise_c_candidates.py`)을 해서 우선일 전 공개만 5건까지 고르고(`eval/retrieval/noise_c.py`), KIPRIS Plus 공개·공고 전문(`scripts/fetch_noise_c_pdfs.py`, Open API 무료 옵션)으로 받았다. 115개 모두 `%PDF`·글자층 있음. 검색·전문 응답은 `work/kipris_c/`·`work/kipris_c_fulltext/`(git 밖, 모두 resultCode 00). 어느 OA의 노이즈인지는 풀 표 `cite_pool_bc.yaml`의 `only_oas` (git 밖). 드라이브에는 아직 안 올렸다.
- 11/22 [#229](https://github.com/merge-mates/patent-ai-workspace/issues/229) tune 102건 늘리기: 더한 72건 중 인용문헌이 있는 71건(1건은 공보에 심사관 인용(Y) 표시가 없다)의 공보 177개(한국 160, 미국 17. 같은 문헌을 여러 사건이 인용해 고유 문헌은 173)를 받았다, 255MB. 번호는 공보 TXT의 심사관 인용(Y) 목록에서 뽑고, 모두 Google Patents 공보 PDF로 받았다 (#168과 같은 방법, 1초 간격, `%PDF` 확인, 은진 맥. 스크립트는 git 밖 `work/t229/fetch_cited_t229.py`).
  - 비특허 문헌 7건 (11/23): 6건 받음. 5건은 arXiv에서 OA에 적힌 날짜와 같은 판, 1건은 HAL 공개 판이고 같은 사건 폴더에 `NPL<번호>_<짧은 제목>_<출처>.pdf`로 넣었다. 못 받음 1건: 학회 논문집(SPIE) 유료, 무료 판 없음. 그래서 184개 중 183개 ([#268](https://github.com/merge-mates/patent-ai-workspace/issues/268)).
  - 색인: 아직 안 넣었다. `cite-idx-v4`에 더하지 않고 새 판 `cite-idx-v5`로 따로 만든다 (v4 점수 비교를 남기려고, 11/22 은진). 넣는 사람과 때는 확인 중이다 (정답 판 3·#178 재측정 뒤, #268).
  - 드라이브 `02_인용문헌/tune_1118/cited_v2/` 사본은 아직 없다 (출원번호가 든 폴더라 은진이 올린다).
- 쪽 수: 한국 공보 9~37쪽, 논문 학회판 9쪽, 다른 판 12쪽.
- 검색 정답(`data/goldsets/tune/search_v0/`)은 tune 10건을 다루지만, 2건은 거절이유가 42조뿐이라 인용문헌이 없어 폴더도 없다.

## 3. 품질
- 같은 문헌의 쪽마다 공보 번호·쪽 번호 줄이 되풀이된다 (청킹 전에 뺌, 뺀 줄 수는 색인 보고).
- 논문 두 판: 학회판(9쪽, OA가 짚은 학회 쪽 범위와 같음)과 원고판(12쪽). 색인은 학회판만 쓴다 (어느 파일인지는 git 밖 `file_doc_ids.yaml`).
- 질의(OA 당시 청구항)는 `data/processed/cases/<출원번호>/<발송번호>/`의 청구항이력·행정이력에서 만든다 (검색 정답 변환 `eval/retrieval/cite_gold.yaml`의 `cases_root`). 11/22 옛 자리로 만든 정답과 줄 105개가 바이트까지 같았다 (#159).
- 그 전에는 옛 `data/raw/cases/<출원번호>/`에서 만들었다. 이 폴더는 사람마다 든 것이 달라(은진 맥 8건은 이력 두 파일만, 재아 맥 9건은 정답 서류까지) 받은 묶음이 `case_full/`에 있는지 확인한 뒤 각자 지운다 (#159).
- 사건 자료 받은 묶음 전체(등록공보·결정서·결정본문·OA 뒤 의견서·보정서, 이력 전체 판)는 채점 확인용으로 `data/goldsets/tune/case_full/<출원번호>/`에 둔다. AI 입력은 `scripts/split_cases_at_oa.py`가 OA 시점까지 자른 `data/processed/cases/<출원번호>/<발송번호>/`만 쓴다 (#148). 번호가 없어 시점을 모르는 공개공보·등록공보는 입력에 없다. 예외로 출원서가 입력에 없는 사건(PCT 국내단계)은 공개일이 OA 발송일보다 앞선 공개공보를 최초 명세서로 넣는다 (PRD 표 163줄, tune 2건).
- 글자층 품질 (11/19 첫 색인 `cite-idx-v1`): 한국 공보 15건 중 1건(2007년 공개공보)은 글자층에 식별번호가 하나도 없다 (본문 조각 안 만듦). 1건은 식별번호 14개가 글자층에 아예 없다 (마커 글자 자체가 없음, 3개 확인, 청킹 문제 아님). 또 1건은 식별번호 12개가 마커만 있고 글자가 없다 (그림·수식 문단으로 봄, "빈 조각" 경고). 원문과는 아직 대조 안 함 [확인 필요: 원문 대조]
- 머리말·꼬리말로 뺀 줄: 685줄 (식별번호 줄은 0줄 빠짐)

## 4. 가공
- raw → 색인: `PdfplumberExtractor.extract` → 머리말·꼬리말 빼기 → 청킹 → `cite_chunks` (설계 [cite-search design](../features/cite-search/design.md) 2절)
- 결과 위치: Postgres `cite_chunks` (색인 판 `cite-idx-v1`), 덤프 `data/index/cite-idx-v1.dump`, 색인 보고 `work/cite_search/`

## 5. 쓰면 안 되는 곳
- git, 공개 배포, 테스트 fixture (fixture는 지어낸 글자만).
- 미검토 외부 모델 전송은 architecture.md 표를 따른다.
