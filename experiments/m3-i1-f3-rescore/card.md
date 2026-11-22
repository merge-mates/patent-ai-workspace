---
실험: m3-i1-f3-rescore
기능: F3
담당: 재아
날짜: 2026-11-22
기준선: experiments/m2-f3-skeleton/
평가 세트: tune 10건 (VERSION 2. 검색 정답 retrieval/cite_gold.jsonl + F1 정답의 clarity_terms, gold_sha256 0fee10d3… 기준선과 같음)
바꾼 것: 코드 판 (m2-f3-skeleton 849d18f 뼈대 → main 9eb8237: 부모 구성요소 넣기·second_search 기본 켬 등 그 사이 머지된 F3). 설정은 그 판의 config/f3.yaml 그대로
주 지표: search_recall
---
# F3 다시 채점: main 9eb8237로 tune 같은 설정 3회 (이슈 #39·#30)

**가설**: 없음. 기준선(뼈대 첫 실행, 1회) 뒤 머지된 F3로 점수가 어디쯤인지, 같은 설정에서 얼마나 흔들리는지 잰다.
**종류**: 다시 재기 (코드 판만 다름, 같은 설정 3회)
**설정**: main 9eb8237 `config/f3.yaml` 그대로 (claude-haiku-5-5, effort medium, max_tokens 64000, impl `split_search`, 검색 hybrid RRF·cite-idx-v2·k 10, `second_search: true`). 채점 실행이라 `use_examiner_paragraphs`만 false (심사관 지정 번호를 입력에 주지 않음).
- 실행: git 밖 `work/overnight_1121/scripts/f3_run.py` (11/20 스크립트에 `--cache-dir`만 더함: 회차마다 새 캐시라 2·3회차가 1회차 답을 다시 쓰지 않음). 예측은 git 밖 `work/overnight_1121/runs/f3_run{1,2,3}/`.
- 입력: F1 결과는 기준선과 같은 `work/overnight_1120/f1/a3_run2_pred` (m1-i3-f1-stream-64k 2회차). case10은 F1 예측이 없어 3회 모두 예측 없음 0점 (기준선과 같음).
- scores.json은 1회차. 2·3회차는 git 밖 `work/overnight_1121/runs/score_f3_run{2,3}/scores.json`.
- **이 점수는 #213(머지됨)·#211(코드 세션 작업 중, 묶음 하나 실패를 그 묶음만 보류) 앞 판이다.** #211이 들어가면 아래 1회차 case2처럼 사건 전체가 실패하는 일이 줄어 점수가 달라질 수 있다.

## 결과 (n=10, 같은 설정 3회)
| 지표 | 기준선 (m2, 1회) | 1회 | 2회 | 3회 | 평균 | 최소~최대 |
|---|---|---|---|---|---|---|
| search_recall (주 지표) | 0.584 | 0.585 | 0.619 | 0.656 | **0.620** | 0.585~0.656 |
| search_hit | 0.732 | 0.711 | 0.765 | 0.794 | 0.757 | 0.711~0.794 |
| selected_recall | 0.186 | 0.165 | 0.183 | 0.196 | 0.181 | 0.165~0.196 |
| selected_hit | 0.378 | 0.338 | 0.334 | 0.380 | 0.351 | 0.334~0.380 |
| random_search_recall | 0.262 | 0.273 | 0.316 | 0.320 | 0.303 | |
| search_recall_ratio (무작위 대비) | 2.23 | 2.14 | 1.96 | 2.05 | 2.05 | 1.96~2.14 |
| clarity_term_reviewed | 0.694 | 0.583 | 0.694 | 0.694 | 0.657 | 0.583~0.694 |
| novelty_tables | 3 | 2 | 3 | 3 | | |
| 예측 없음 (missing_prediction) | 1 | 2 | 1 | 1 | | |
| CQ 후보 | 14 | 4 | 10 | 10 | | |

- 신규성 한 문헌 규칙 위반(novelty_multi_citation) 3회 모두 0. 재지 않은 지표 5개(정답 없음)는 기준선과 같음.
- 한 줄: tune v2 F3 main 9eb8237 3회 search_recall 0.620 (0.585~0.656) · search_hit 0.757 · selected_recall 0.181 · selected_hit 0.351, 3회 $0.980.

### 실패·다시 부름 (회차별)
| 회차 | 끝난 사건 | 실패한 사건 (원인) | 출력 검사 실패로 다시 부른 단계 |
|---|---|---|---|
| 1 | 8/10 | case2 (`f3.split_elements` 두 번 다 JSON 아님 → `ModelOutputInvalid`로 사건 전체 실패), case10 (F1 예측 없음) | case2 split_elements 1 |
| 2 | 9/10 | case10 | case2 split_elements 1 (두 번째에 통과) |
| 3 | 9/10 | case10 | case7·case8 split_elements 각 1 |

### 원인 표 (기준선과 다른 칸)
| 칸 | 차이 | 원인 한 줄 | 근거 |
|---|---|---|---|
| 1회 search_hit·selected_*·clarity·novelty_tables | 1회만 낮음 | case2가 사건 전체 실패로 0점 (2·3회는 통과). 모델 답(JSON 아님) → 코드가 묶음만 보류하지 않고 run 실패 (#211이 고치는 곳) | `runs/f3_run1/<case2>.error.txt` (`elements.py:270` → `retry.py:54` → `client.py:252`) |
| selected_hit 평균 0.351 < 기준선 0.378 | 3회 범위(0.334~0.380)가 기준선을 포함 | 흔들림 안. 원인을 가를 만큼 차이가 크지 않음 | 위 표 |
| search_recall 평균 0.620 > 0.584 | 3회 모두 기준선 이상 | 짐작: second_search 켬(1차에 못 찾은 구성요소를 20개 더 봄)과 부모 구성요소 넣기. 켬/끔을 따로 재지 않아 나누지 못함 | config/f3.yaml `second_search: true` |

## 호출·비용
| 회차 | 모델 호출 (Haiku) | 입력 토큰 | 출력 토큰 | 비용 ($) |
|---|---|---|---|---|
| 1 | 198 | 1,108,196 | 322,158 | 0.272 |
| 2 | 245 | 1,531,255 | 428,717 | 0.368 |
| 3 | 241 | 1,473,098 | 385,524 | 0.340 |
- 단가 Haiku 5.5 $0.10/$0.50 per MTok (요청 10만 토큰 이하, claude-api 스킬 모델 표 2026-11-03) + 질의 임베딩 text-embedding-3-small 회차마다 약 6~8천 토큰 ($0.0002 아래). scores.json `cost`는 채점기 비용 0.
- 합 $0.980 (3회).

## 해석 (Claude 초안, 사람이 고칠 것)
- 검색(search_recall)은 기준선보다 3회 모두 높다 (+0.001~+0.072). 고르기(selected_*)는 기준선과 흔들림 안에서 같다 → LLM이 대비 근거로 고르는 단계가 여전히 병목 (selected_recall ≈ 0.18, 검색이 가져온 것의 약 30%).
- 같은 설정 흔들림이 크다 (search_recall 범위 0.07, clarity 0.11). 사건 하나가 통째로 실패하면 10건 평균이 크게 흔들린다 → #211 뒤 다시 재면 흔들림이 줄어드는지 본다.
- 이 점수는 #211 앞 판이고, F2가 없다.

## 다시 내는 법
- 실행: `cd <main worktree> && uv run python <repo>/work/overnight_1121/scripts/f3_run.py <out> --workers 4 --cache-dir <회차 캐시>` (git 밖. 키는 .env에서 환경 변수로만)
- 채점: `uv run python eval/run_eval.py --config experiments/m3-i1-f3-rescore/config.yaml --predictions <out>`
