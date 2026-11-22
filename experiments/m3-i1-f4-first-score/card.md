---
실험: m3-i1-f4-first-score
기능: F4
담당: 재아
날짜: 2026-11-22
기준선: experiments/m3-f4-skeleton/ (점수 없음: 그때는 F4 정답이 없었다)
평가 세트: tune 10건 (VERSION 2, F4 정답 data/goldsets/tune/f4/ 10건, gold_sha256 1db0bf96…)
바꾼 것: 코드 판 (m3-f4-skeleton 1731de3 → main 9eb8237)과 `final_rejection_limit` 기본값 false → true. 처음으로 F4 정답으로 채점
주 지표: direction_top1
---
# F4 첫 점수: main 9eb8237로 tune 같은 설정 3회 (이슈 #39·#30)

**가설**: 없음. F4 정답이 생긴 뒤 처음 재는 점수와, 같은 설정 흔들림.
**종류**: 기준선 (첫 점수)
**설정**: main 9eb8237 `config/f4.yaml` 그대로 (claude-haiku-5-5, effort medium, max_tokens 64000, 후보 최대 3, `final_rejection_limit: true`).
- 입력: F3 결과는 `m3-i1-f3-rescore` **1회차** (git 밖 `work/overnight_1121/runs/f3_run1/`, 3회 모두 같은 F3 입력). F1 결과는 `work/overnight_1120/f1/a3_run2_pred`. **F2(법률 근거)는 없음** → 빈 묶음 "확인되지 않음".
- 사건: tune 10건 중 8건. case10(F1 예측 없음)과 F3 1회차에서 실패한 사건 1건은 F3 결과가 없어 F4 예측 없음 → 0점 (`missing_prediction` 2).
- 실행: git 밖 `work/overnight_1121/scripts/f4_run.py` (11/20 스크립트에 `--cache-dir`만 더함, 회차마다 새 캐시). 예측 `work/overnight_1121/runs/f4_run{1,2,3}/`. scores.json은 1회차, 2·3회차는 `runs/score_f4_run{2,3}/`.
- **이 점수는 #213(머지됨)·#211(작업 중) 앞 판이고, F2 없이 낸 값이다.**

## 결과 (n=10 OA, 같은 설정 3회)
| 지표 | 1회 | 2회 | 3회 | 평균 | 최소~최대 |
|---|---|---|---|---|---|
| **direction_top1** (주 지표, 목록 첫째 후보) | 0.104 | 0.136 | 0.079 | **0.106** | 0.079~0.136 |
| direction_top1_with_inherited | 0.128 | 0.163 | 0.103 | 0.132 | 0.103~0.163 |
| direction_top1_ranked_only (순위 1 후보, 보류 줄 뺌) | 0.485 | 0.274 | 0.339 | 0.366 | 0.274~0.485 |
| needs_human_judgment_rate (보류 비율) | 0.013 | 0.027 | 0.027 | 0.022 | |
| direction_top1_conf_high | - | - | - | - | 1번 후보가 high인 줄 0개 (지표 뺌) |
| direction_top1_conf_medium | 0.000 | - (줄 없음) | 0.000 | 0.000 | |
| direction_top1_conf_low | 0.139 | 0.170 | 0.119 | 0.143 | |
| 누락 쌍 (uncovered_pairs) | 0 | 0 | 0 | | |
| 예측 없음 / 후보 0개 묶음 / ranked_only에서 뺀 보류 줄 | 2 / 0 / 3 | 2 / 0 / 3 | 2 / 0 / 3 | | |

- 한 줄: tune v2 F4 main 9eb8237 3회 direction_top1 0.106 (0.079~0.136) · ranked_only 0.366 (0.274~0.485) · 보류 0.022 · 누락 쌍 0, F2 없음, 3회 $0.752.

- 새 정의(11/22 결정 2, AI 기본 선택)로 다시 채점: direction_top1 0.479 / 0.240 / 0.303 (평균 0.341), direction_top1_list_first 0.104 / 0.136 / 0.079 (옛 값과 같음). 같은 예측 3회를 채점기만 바꿔 다시 잼. 위 표와 scores.json은 옛 정의 그대로다 (다시 채점 결과 git 밖 `work/overnight_1121/runs/score_f4_run{1,2,3}_rankdef/`).

### 1번 후보(목록 첫째)와 순위 1 후보의 확신도 (판단 단위 30개 × 3회, 예측 JSON에서 셈)
| 회차 | 목록 첫째: low / medium / high | 순위 1 후보: medium / high / 없음(보류) |
|---|---|---|
| 1 | 28 / 2 / 0 | 27 / 0 / 3 |
| 2 | 29 / 1 / 0 | 28 / 0 / 2 |
| 3 | 25 / 5 / 0 | 28 / 0 / 2 |

### 원인 표 (direction_top1이 낮은 칸)
| 칸 | 원인 한 줄 | 근거 |
|---|---|---|
| direction_top1 0.106 vs ranked_only 0.366 | 모델이 목록 첫째에 확신 low(순위 없음) 후보를 둔다 (90단위 중 82). 프롬프트가 "low인 후보도 먼저 볼 것을 앞에" 두라고 하고, 채점기는 목록 첫째를 1번 후보로 센다. 그래서 주 지표는 대개 low 후보의 방향을 잰다 | `prompts/f4/direction.md:15-16`, `eval/f4/score.py:5-9`, `core/f4_response_draft/directions.py:269` (AI 기본값은 rank==1 후보) |
| conf_medium 0.000 | 목록 첫째가 medium인 줄이 회차마다 0~5단위뿐이라 줄 수가 너무 적다 | 위 확신도 표 |
| conf_high 없음 | 모델이 high를 한 번도 내지 않음 (F2 없음 → 근거가 "확인되지 않음"이라 짐작) | 짐작: `config/f4.yaml` 상한 아님, 모델 답 확신도 값 |

## 호출·비용
| 회차 | 모델 호출 (Haiku) | 입력 토큰 | 출력 토큰 | 출력 검사 실패로 다시 부름 | 비용 ($) |
|---|---|---|---|---|---|
| 1 | 77 | 1,006,819 | 284,722 | 1 (f4.direction) | 0.243 |
| 2 | 78 | 1,030,997 | 286,028 | 1 (f4.direction) | 0.246 |
| 3 | 83 | 1,087,964 | 307,552 | 4 (f4.direction) | 0.263 |
- 단가 Haiku 5.5 $0.10/$0.50 per MTok (claude-api 스킬 모델 표 2026-11-03). 합 $0.752. scores.json `cost`는 채점기 비용 0.

## 해석 (Claude 초안, 사람이 고칠 것)
- 주 지표 0.106은 "모델이 목록 첫째에 둔 후보"를 재는데, 그 자리는 대개 확신 low 후보다. 화면·AI 기본값이 쓰는 순위 1 후보로 재면 0.366이다. 주 지표 정의(목록 첫째 vs 순위 1)와 프롬프트의 목록 순서 규칙 중 어느 쪽을 맞출지는 [사람 판단] (research/46_interview_questions.md Q3 "direction_top1 문턱"과 같이).
- ranked_only의 흔들림이 크다 (0.274~0.485). 줄 수가 적어(OA 10, 그중 예측 8) 한두 묶음 차이로 크게 움직인다.
- 꼭 지킬 선: 누락 쌍 3회 모두 0, 후보 0개 묶음 0.
- F2(법률 근거) 없이 낸 값이라 F2 연결(#222) 뒤 다시 잰다.

## 다시 내는 법
- 실행: `uv run python <repo>/work/overnight_1121/scripts/f4_run.py <out> --workers 4 --f3-dir <F3 실행 폴더> --cache-dir <회차 캐시>` (git 밖)
- 채점: `uv run python eval/run_eval.py --config experiments/m3-i1-f4-first-score/config.yaml --predictions <out>`
