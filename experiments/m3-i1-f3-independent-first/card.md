---
실험: m3-i1-f3-independent-first
기능: F3
담당: 재아
날짜: 2026-11-22
기준선: m3-i1-f3-rescore (브랜치 chore/39-f4-first-score, main 9eb8237 3회)
평가 세트: tune 10건 (VERSION 2, gold_sha256 0fee10d3… 기준선과 같음)
바꾼 것: 코드 (이슈 #30 남은 일 ②, feat/30-f3-independent-first): 진보성은 대표 청구항(독립항) 먼저 대비하고 차이점이 있으면 종속항은 **검색은 하고 LLM 대비만 생략**(11/22 재아 결정 1 (나), 18603a9) + 명세서 효과 반박 후보. 채점기는 건너뛴 줄을 selected_* 분모에서 빼고 따로 셈(f65f910). #211(f499f2c) 위
주 지표: search_recall
---
# F3 대표 청구항 먼저 + 효과 후보: tune 같은 설정 2회 (이슈 #30)

**가설**: 독립항에 차이점이 있으면 종속항의 LLM 대비만 건너뛰어 호출·비용이 줄고, 검색 회수와 대비한 줄의 품질은 그대로다.
**종류**: 코드 비교 (설정 그대로)
**설정**: `config/f3.yaml` 그대로 (claude-haiku-5-5, effort medium, max_tokens 64000, split_search, hybrid RRF·cite-idx-v2·k 10, second_search true, compare_variant standard). 채점 실행이라 `use_examiner_paragraphs`만 false.
- 코드 f65f910 (18603a9 + 채점기). 실행: git 밖 `work/overnight_1121/scripts/f3_run.py` (회차마다 새 캐시), 예측 `work/overnight_1121/runs/f3_30b_run{1,2}/`. F1 입력은 기준선과 같은 `work/overnight_1120/f1/a3_run2_pred`. case10 F1 예측 없음 (기준선과 같음).
- **기준선도 같은 채점기(f65f910)로 다시 셈**: m3-i1-f3-rescore 3회 예측(`runs/f3_run{1,2,3}`)을 새 채점기로 채점 (`runs/score_f3_run{N}_new`). 기준선에는 건너뛴 줄이 없어 selected_*는 옛 값과 같다.
- 건너뛴 종속항은 2차 검색(second_search)을 하지 않으므로 검색 회수 비교는 `search_recall_round1`(1차 검색만)을 같이 본다.
- scores.json은 1회차, 2회차 git 밖 `runs/score_f3_30b_run2/scores.json`.
- (지난 판 8382103, 종속항 검색도 안 함: search_recall 0.337·0.344, 검색 기록 없는 줄 6 → 43. git 밖 `runs/score_f3_30_run{1,2}`. 11/22 결정 1로 이 판으로 바꿈.)

## 결과 (n=10)
| 지표 | 기준선 3회 (새 채점기, 최소~최대 · 평균) | 이번 1회 | 이번 2회 | 이번 평균 |
|---|---|---|---|---|
| search_recall (주 지표) | 0.585~0.656 · 0.620 | 0.637 | 0.580 | **0.609** |
| search_recall_round1 (1차 검색만) | 0.534~0.586 · 0.567 | 0.595 | 0.572 | 0.584 |
| search_hit | 0.711~0.794 · 0.757 | 0.775 | 0.725 | 0.750 |
| selected_recall (건너뛴 줄 뺌) | 0.165~0.196 · 0.181 | 0.216 | 0.139 | 0.178 |
| selected_recall_incl_skipped (옛 셈법) | 0.165~0.196 | 0.101 | 0.070 | 0.086 |
| selected_hit | 0.334~0.380 · 0.351 | 0.402 | 0.343 | 0.373 |
| search_recall_ratio (무작위 대비) | 1.96~2.14 | 2.20 | 2.01 | |
| clarity_term_reviewed | 0.583~0.694 | 0.694 | 0.694 | |
| novelty_tables | 2~3 | 3 | 3 | |
| 검색 기록 없는 정답 줄 (not_searched_rows) | 6 | **6** | **6** | |
| 대비를 건너뛴 종속항 정답 줄 (skipped_dependent_rows) | 0 | 42 | 42 | |
| CQ 후보 | 4 / 10 / 10 | 12 | 15 | |
| 예측 없음 | 2 / 1 / 1 | 1 | 1 | |

## 원인 표 (기준선과 다른 칸)
| 칸 | 원인 한 줄 | 근거 |
|---|---|---|
| selected_recall_incl_skipped 0.086 | 건너뛴 종속항 42줄은 LLM이 고르지 않아 옛 셈법에서는 0점 (설계대로). 새 주 셈법(selected_recall)은 그 줄을 분모에서 뺌 | `failures.skipped_dependent_rows` 42, f65f910 |
| CQ 후보 4~10 → 12~15 | 건너뛴 종속항도 검색 기록이 생겨 CQ 셈(검색했는데 못 찾음)에 들어옴. 기록이 없던 줄이 CQ로 옮겨 옴 | not_searched_rows 43(지난 판) → 6 |
| search_recall 평균 0.609 < 0.620 | 2회 범위(0.580~0.637)가 기준선 범위(0.585~0.656) 안. 흔들림 안 | 위 표 |

## 호출·비용
| 회차 | 끝난 사건 | 모델 호출 (Haiku) | 입력 토큰 | 출력 토큰 | 출력 검사 실패 | 비용 ($) |
|---|---|---|---|---|---|---|
| 1 | 9/10 | 176 | 904,522 | 354,535 | 5 | 0.268 |
| 2 | 9/10 | 182 | 1,008,905 | 377,253 | 5 | 0.290 |
- 기준선 3회 평균 호출 228회·$0.327 → 이번 179회·$0.279 (호출 −22%, 비용 −15%). 단가 Haiku 5.5 $0.10/$0.50 per MTok. 합 $0.558.
- 한 줄: tune v2 F3 #30 대표 청구항 먼저(종속항 검색은 함) 2회 search_recall 0.637·0.580 (기준선 3회 0.585~0.656), 검색 기록 없는 줄 6 그대로, 건너뛴 종속항 42줄 따로 셈, 호출 −22%, $0.558.

## 해석 (Claude 초안, 사람이 고칠 것)
- (나)로 고친 뒤 검색 회수는 기준선 흔들림 안으로 돌아왔다 (search_recall·round1·search_hit). 건너뛴 종속항도 후보 문단이 남는다 (11/22 결정 1의 이유와 같음).
- 대비한 줄의 고르기(selected_recall, 건너뛴 줄 뺌)는 0.216·0.139로 흔들림이 크다. 기준선(0.181)과는 **분모가 달라 직접 비교할 수 없다**: 이번 값은 건너뛴 종속항 42줄을 분모에서 뺐고(`eval/f3/score.py` `if not skipped_dep:`), 정답 줄이 모두 건너뛴 줄인 OA는 평균에서 통째로 빠진다. 기준선은 그 줄을 포함한다. "대비한 줄 품질이 그대로"인지는 기준선 3회 예측을 같은 (OA, 청구항) 줄을 빼고 다시 채점해야 말할 수 있다.
- 사람이 받는 근거 문단으로 보면 모든 정답 줄을 분모로 센 `selected_recall_incl_skipped`가 0.086으로 기준선 0.181의 약 절반이다. 건너뛴 종속항은 LLM이 근거를 고르지 않아서다 (검색 후보는 남음, 11/22 결정 1 (나)).
- 호출 −22%는 유지된다.
- 남은 것: ADR 0001:30 신규성 순서와 어긋남은 그대로 (11/22 결정 1에 적힘).

## 다시 내는 법
- 실행: `uv run python <repo>/work/overnight_1121/scripts/f3_run.py <out> --workers 4 --cache-dir <회차 캐시>` (이 브랜치 worktree에서)
- 채점: `uv run python eval/run_eval.py --config experiments/m3-i1-f3-independent-first/config.yaml --predictions <out>`
