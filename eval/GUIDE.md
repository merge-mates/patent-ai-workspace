# 정답 파일 형식과 위치 (eval/GUIDE.md)

정답을 **어디에 어떤 꼴로** 두는지만 적는다. 정답을 뽑는 규칙·지표·애매한 경우는 [docs/evaluation/](../docs/evaluation/README.md), 평가 원칙은 [product.md](../docs/product.md) 6절, 채점 때 지킬 규칙은 [.claude/rules/eval.md](../.claude/rules/eval.md). 아래 예시의 번호는 모두 만든 값이다.

## 1. 어디에 두나
- 정답은 git 밖 `data/goldsets/`에만 둔다. 저장소에는 출원번호·발송번호·원문 글자를 넣지 않는다 (파일 이름에 출원번호가 들어가므로 파일 목록도 커밋하지 않는다).
- `data/goldsets/`는 채점기(`eval/`)만 읽는다. 앱 코드(`src/`)는 불러오지 않는다.
- 정답을 드러내는 서류(그 OA에 낸 의견서·보정서, 등록공보, 결정서·결정본문 등 대상 OA 뒤 서류)는 AI 입력 폴더에 두지 않는다. 입력 폴더에 섞이면 AI가 정답을 보게 된다. "AI 입력으로 쓰지 않는다"는 문장만으로 막지 않고 폴더로 가른다 (#150 1번, 11/20).
  - 받은 사건 묶음 전체(위 서류, 이력 전체 판)는 정답 쪽 `data/goldsets/<세트>/case_full/<출원번호>/`에 그대로 둔다. F4 정답을 뽑는 재료도 여기서 읽는다.
  - AI 입력은 스크립트가 OA 시점까지 잘라 `data/processed/cases/<출원번호>/<발송번호>/`에 만든다 (#148, `scripts/split_cases_at_oa.py`). 청구항이력은 OA 앞 판만 남는다.
  - 검색 정답 변환(`eval/retrieval/cite_gold.yaml`의 `cases_root`)도 이 입력 폴더에서 질의를 만든다 (#159).

```
data/goldsets/
├── VERSION                  정수 하나 (지금 2)
├── tune/                    개발 중에 보는 세트
│   ├── f1/                  F1 통지서 읽기: OA 한 통에 JSON 하나 (<출원번호>_<발송번호>.json)
│   ├── retrieval/           F2·F3 검색: cite_gold.jsonl, law_gold.jsonl, cite_doc_ids.yaml, cite_pool.yaml·cite_noise_b.jsonl(#178 둘째 점수 범위)
│   ├── case_full/           받은 사건 묶음 전체 (정답 쪽, AI 입력 아님, #148)
│   ├── search_v0/           검색 정답을 만든 검수본 (retrieval/ 파일의 재료, 드라이브 이름 `tune_search_v0/`)
│   └── f4/                  F4 대응 방향 (아직 없음, 6절)
└── report/                  보고용. M3 끝(11/26)에 채점기만 읽는다 (개발하는 세션은 열지 않음. 만드는 법은 아래 report 정답 절)
```
- `report/`는 `tune/`과 폴더 구조·파일 꼴이 같다. 다른 것은 보는 때뿐이다.

## 2. 버전 (`data/goldsets/VERSION`)
- 정수 하나. 실험 설정의 `goldset_version`과 정답 파일 안 `gold_version`이 이 값과 다르면 채점기가 멈춘다 (`eval/common/goldset.py`).
- 지금 판은 2 (11/19 검색 정답 "같은 이유" 고침으로 올림). 정답을 고치면 판을 올리고, 바꾼 이유를 커밋 본문에 쓴다 (`.claude/rules/eval.md`). 예외는 F1 정답(`f1/`) 하나다: #20 F1 첫 점수 전까지는 `f1/`의 칸 추가·원문 글자 고침을 같은 판으로 둔다 (아직 F1 점수가 없어서 섞일 점수가 없음). 검색 정답(`retrieval/`)은 이미 판 2로 점수가 나와 있어 예외가 없다. 판이 다른 점수끼리는 비교하지 않는다.

## 3. 평가 세트 목록 (어떤 OA를 쓰나)
- 한 줄 = OA 한 통 (출원번호 + 발송번호). tune / report / 대기열 / 실패 사례 칸과 그룹(진보성만 / 명확성만 / 섞임(신규성 포함) / 섞임(신규성 없음) / 지원 안 하는 이유 섞임)을 적는다 (product.md 6.1절).
- 목록은 출원번호가 있어서 git에 올리지 않는다. 팀 드라이브 한 곳에 두고, 판을 바꾸면 파일 이름에 판을 붙인다 (예: `v2e_selected_1118.csv`).
- 위치: 드라이브 `04_KIPRIS_대량원본/oa_learning_scan_1116/v2f_selected_1121.csv` (지금 쓰는 v2f 목록, 149 = report 119 + tune 30. 그 전 판 v2e 129는 같은 폴더). 서류는 `01_OA_사건자료_v2/`(report는 `_report/`, 봉인). 11/17 회의의 `05_평가정답/` 제안 대신 이미 있는 곳으로 정했다 (11/19 은진).
- 세트에 넣는 OA (product.md 6.1·7절과 같음): 지원 거절이유(진보성·명확성·신규성)가 있다 / 특허 인용은 한국·미국만 (다른 나라 특허가 인용되면 뺌, 비특허 문헌은 허용) / 대응 바로 다음 서류가 등록결정이다 / 출원 이력을 확인했다.

## 4. 기능별 정답 파일
| 기능 | 파일 | 한 줄(한 파일) | 형식 정의 | 형식 검사 |
|---|---|---|---|---|
| F1 통지서 읽기 | `<세트>/f1/<출원번호>_<발송번호>.json` | OA 한 통 | [f1-oa-gold.md](../docs/evaluation/f1-oa-gold.md) 4절 | `eval/f1/gold.py` |
| F3 인용문헌 문단 검색 | `<세트>/retrieval/cite_gold.jsonl` | 거절이유 × 청구항 × 인용문헌 | [retrieval design](../docs/features/retrieval/design.md) 7-1 | `eval/retrieval/gold.py` |
| F2 법령 검색 | `<세트>/retrieval/law_gold.jsonl` | OA 거절이유 하나 | [retrieval design](../docs/features/retrieval/design.md) 7-1 | `eval/retrieval/gold.py` |
| F4 대응 방향 | `<세트>/f4/<출원번호>_<발송번호>.json` | OA 한 통 (안에 청구항 줄) | [f4-direction-gold.md](../docs/evaluation/f4-direction-gold.md) 4절 (초안) | `eval/f4/gold.py` (①②층 채점은 `eval/f4/score.py`) |

- F4 채점의 예측 폴더(git 밖)는 정답과 같은 이름 `<출원번호>_<발송번호>.json`(`run_f4` 결과 또는 `DirectionCandidates` 목록)을 둔다. 판단 단위는 결과 안의 `units` 칸을 쓰고, 없을 때만(옛 결과·목록만 둔 파일) `<출원번호>_<발송번호>.units.json`을 읽는다 (둘 다 없으면 채점 실패). 이름이 `<숫자>_<숫자>` 꼴이 아닌 `.json`(실행 요약 `summary.json` 등)은 건너뛰고 경고한다. 정답 폴더가 없으면 채점기는 점수를 쓰지 않고 "정답 없음"(종료 코드 3)으로 끝난다. `direction_top1`은 모델 1번 후보(후보 목록 첫째)로 보류 묶음도 세고(후보 0개 묶음은 틀림), 순위 1 후보로 보류 줄을 뺀 값은 `direction_top1_ranked_only`로 따로 낸다. 확신도별 `direction_top1_conf_*`와 `needs_human_judgment_rate`를 같이 본다. ①층 다룸 지표(`handled_accuracy`)는 정답 문서에서 정의를 정한 뒤 다시 넣는다 (지금은 출력에 없음).
- 실험 설정은 `goldset: tune`·`goldset_version: 2`·`gold: <세트 안 경로>`로 고른다. `gold`에 `..`·절대 경로는 못 쓴다 (`eval/common/goldset.py`).
- 채점 단위는 기능마다 위 "한 줄"이고, 세트 점수는 OA 한 통을 한 표로 모은다 (청구항 점수 → OA 평균 → 세트 평균). 자세한 건 각 형식 문서.
- 검색 정답에서 채점 범위 밖 줄을 빼는 규칙(`exclude`)은 retrieval design 7-1을 따른다. 정답 항목에 맞는 조각이 검색 범위에 하나도 없으면 그 항목을 빼고(모두 없으면 줄째, `excluded_gold_not_in_scope`·`excluded_gold_items_not_in_scope`, #138) 건수를 `failures`에 남긴다. 정답 파일은 고치지 않는다 (채점기가 셈).

### 인용문헌 둘째 점수 풀 표 (`<세트>/retrieval/cite_pool.yaml`, #178)
- 노이즈 범위(`cite_noise_b.jsonl`)의 재료다. `uv run python -m eval.retrieval.noise_scope`가 이 표와 `cite_gold.jsonl`로 범위를 만든다 (넣는 조건은 [search-gold.md](../docs/evaluation/search-gold.md) 5절). 정답이 아니라서 VERSION과 따로 간다.
- 칸 (형식 검사는 `eval/retrieval/noise_scope.py` `PoolTable`):
  - `docs.<doc_id>`: `app_no` = 그 공보의 출원번호(숫자만, 같은 특허 가리기. 비특허는 `null`), `date` = 공개공보는 공개일, 등록공보는 등록공고일 (`YYYY-MM-DD`). 풀 = 여기 적은 문헌 전체.
  - `oas.<발송번호>`: `app_no` = 그 OA를 받은 출원의 출원번호, `priority_date` = 우선일 (우선권 주장이 없으면 출원일).
  - 정답 줄의 발송번호·정답 문헌이 표에 없거나, 특허 문헌에 `app_no`가 없으면 멈춘다.
- 11/21 표(tune v2, 색인 `cite-idx-v1` 문헌 16건, OA 8통)를 만든 법: 공보 PDF 첫 쪽의 (21) 출원번호와 (43) 공개일자·(45) 등록공고일, OA마다 행정이력의 특허출원서 접수일. 8통 모두 출원서에 우선권 주장이 없어 출원일을 우선일로 썼다. 비특허 1건은 날짜를 손으로 넣었다 (비특허는 노이즈로 안 써서 점수 영향 없음). 만드는 스크립트는 #178 T2에서 더한다.
- 공유: 드라이브 `05_평가정답/tune_search_noise_b_1121/`에 `cite_pool.yaml`·`cite_noise_b.jsonl` (출원번호가 있어 git에 넣지 않음). 받은 사람은 `data/goldsets/tune/retrieval/`에 둔다.

### report 정답 만드는 법
- 개발하는 세션(이 저장소에서 프롬프트·설정을 고치는 사람·Claude)은 `report/`를 열지 않는다.
- report 정답과 report AI 입력(OA 시점으로 자른 자료)은 **떨어진 세션**이 만든다: 저장소 밖 폴더에서 새로 연 세션, 이 저장소·프로젝트 기록·공유 메모리 없음, 받는 것은 이 파일의 형식 절(4절과 각 형식 문서)과 report 서류뿐. 결과는 바로 `data/goldsets/report/`에 둔다.
- 사람이 그중 20~30건을 원문으로 검수하고, 검수한 줄 목록을 `report/` 안에 남긴다. 점수표에는 전체 점수와 사람 검수 줄 점수를 따로 보인다 (같은 계열 모델 초안이 AI 답 쪽으로 기울 수 있어서).

## 5. 드라이브 사본
- `data/goldsets/`는 각자 컴퓨터에 있다. 둘이 같은 판을 쓰도록 드라이브에 판마다 사본을 둔다 (`goldsets_v<VERSION>.zip` 꼴) (목록과 같은 `04_KIPRIS_대량원본/` 아래).
- report 사본은 M3 끝(11/26) 채점 때만 내려받는다.

## 6. 아직 없는 것
- F4 대응 방향 정답 파일, ③④층 채점 (M3 전. 형식 검사와 ①②층 채점은 `eval/f4/`. 규칙은 [f4-direction-gold.md](../docs/evaluation/f4-direction-gold.md)).
- F3 명확성·신규성 대비 정답 (M2 설계 때, [f3-compare-gold.md](../docs/evaluation/f3-compare-gold.md)).
