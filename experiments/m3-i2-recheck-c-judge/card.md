---
실험: m3-i2-recheck-c-judge
기능: 근거 다시 찾기 (F3 (가) 인용문헌 다시 찾기, 이슈 #309)
담당: 재아
날짜: 2026-11-23
기준선: experiments/m3-i2-recheck-a/ (같은 커밋 e8076d2 (rebase 전, 다시 찾기 코드는 1b9fb7d와 같음)의 판 A)
평가 세트: tune 10건 (VERSION 2). F3 채점은 검색 정답이 있는 8건
바꾼 것: `recheck: none` → `agent`, `recheck_judge: compare` → `agent` (판정·인용 글자까지 에이전트, 코드는 원문 대조)
주 지표: selected_recall_rechecked
---

> 주 지표 `selected_recall_rechecked`의 비교 대상은 판 A의 2차 기록에 있는 정답 줄 15개다. 채점기는 판마다 대비를 건너뛴 종속항 줄을 빼고, 나머지 줄의 점수를 OA별로 평균한 뒤 OA 평균을 다시 평균한다. 표의 `rechecked_rows` 15는 종속항을 빼기 전 줄 수다.
> **smoke 1회다.** eval 규칙의 "같은 설정 2회 이상"을 채우지 않았다. 판정(design.md 7-3)은 두 사람 환경을 맞춘 뒤 판마다 2회로 한다. 이 카드의 숫자로 C를 쓸지 정하지 않는다 (밤 작업, 재아 아침 확인 전).

## 결과 (smoke 1회, 실행·채점 커밋 e8076d2 (rebase 전, 다시 찾기 코드는 1b9fb7d와 같음), 11/23 10:00~10:25 한 맥에서 판 넷 동시)
| 지표 | A (none) | B (fixed_loop) | C (agent, judge compare) | C-judge (agent, judge agent) |
|---|---|---|---|---|
| search_recall | 0.600 | 0.619 | 0.612 | 0.630 |
| search_recall_round1 | 0.585 | 0.590 | 0.583 | 0.591 |
| selected_recall | 0.219 | 0.134 | 0.114 | 0.150 |
| selected_hit | 0.486 | 0.285 | 0.294 | 0.356 |
| search_recall_rechecked (n=rechecked_rows) | 0.894 | 0.875 | 0.885 | 0.895 |
| selected_recall_rechecked | 0.334 | 0.114 | 0.136 | 0.222 |
| rechecked_rows | 15 | 15 | 15 | 15 |
| F4 direction_top1 | 0.312 | 0.305 | 0.230 | 0.320 |
| 성공 사건 / 전체 | 10 / 10 | 10 / 10 | 10 / 10 | 10 / 10 |
| 모델 호출 수 (전송, 캐시 적중 뺌) | 493 | 689 | 817 | 852 |
|   그중 f3.compare | 50 | 93 | 38 | 36 |
|   그중 recheck.* | {} | {'recheck.rewrite': 39} | {'recheck.agent': 258} | {'recheck.agent': 287} |
| 입력 토큰 / 출력 토큰 | 2440457 / 876532 | 2783096 / 979453 | 3378610 / 834837 | 4278736 / 924131 |
| 비용 $ (계산) | 0.682 | 0.768 | 0.755 | 0.890 |
| 사건 시간 합 / 최대 (초) | 3776.500 / 687.500 | 4275.000 / 802.500 | 3992.100 / 695.000 | 4344.900 / 812.600 |
| 다시 찾은 구성요소 수 | 0 | 55 | 52 | 58 |
| 구성요소당 도구 호출 평균 / 최대 | – / – | 3.000 / 3 | 4.962 / 8 | 5.534 / 8 |
| 끝 상태 (submitted·gave_up·limit_reached·model_call_failed·tool_failed) | {'submitted': 0, 'gave_up': 0, 'limit_reached': 0, 'model_call_failed': 0, 'tool_failed': 0} | {'submitted': 55, 'gave_up': 0, 'limit_reached': 0, 'model_call_failed': 0, 'tool_failed': 0} | {'submitted': 11, 'gave_up': 41, 'limit_reached': 0, 'model_call_failed': 0, 'tool_failed': 0} | {'submitted': 15, 'gave_up': 39, 'limit_reached': 4, 'model_call_failed': 0, 'tool_failed': 0} |
| give_up 비율 | – | 0.000 | 0.788 | 0.672 |

- 비용은 호출 기록의 토큰으로 계산 (Haiku 5.5 $0.10/$0.50 per MTok, 공식 가격표 11/03 판. 임베딩 $0.02 [가정]). 판 넷 합 약 $3.1.
- 판 C는 사건 하나가 F1(OA 읽기) 출력 검사 실패로 멈춰, 같은 판 캐시로 그 사건만 다시 돌려 합쳤다 (첫 시도 기록은 git 밖 `summary_first_try.json`). 다시 찾기 앞 단계라 판 비교 칸에는 영향 없음.
- 상한: 판 넷 모두 실행 스크립트가 `f3.compare`·`f3.compare_recall` 480, `f3.embed` 1200으로 덮음 (config/f3.yaml 240·400은 다시 찾기 몫이 없음, 309b task-4 리뷰 지적).
- F2는 이 DB의 law 색인이 비어 있어 11/23 새벽 실행처럼 빈 결과 (판 넷 같음).
- 노이즈 범위 둘째 점수는 못 잼: cite-idx-v4가 이 맥 DB에 없음 (지시문대로 색인 넣기 안 함).
- 정밀도(정답에 없는 낸 근거의 LLM 판정)는 못 잼: 판정 채점기(309c task-3)를 오늘 밤 만들지 못함.

## 원인 표 (기준선 A보다 떨어진 칸: selected_recall, selected_hit, selected_recall_rechecked, C의 F4 direction_top1)
| 칸 | 짐작한 원인 | 확인한 것 (근거) | 결론 |
|---|---|---|---|
| selected_recall 전체 (A 0.219 / B 0.134 / C 0.114 / C-judge 0.150) | ① 실행마다 흔들렸을 가능성 | 판 A와 같은 설정(fixed_order + second_search)의 11/23 새벽 실행은 0.099 (git 밖 e2e_1123 scores_run1), 이번 A는 0.219. m3-i1-f3-recall-prompt 카드의 같은 설정 3회 결과는 0.200~0.256. 판마다 캐시를 따로 써 1차 대비도 판마다 다시 나옴 | 전체 selected_recall에서도 같은 설정의 점수가 달라졌다. 이 기록으로는 이번 판 차이의 원인을 가르기 어렵다. |
| selected_recall_rechecked (A 0.334 / B 0.114 / C 0.136 / C-judge 0.222) | ② 모름 | 판마다 1회 측정. 비교 대상은 15줄이고, 건너뛴 종속항을 빼고 OA별로 평균한다. | 이번 1회에서는 A가 가장 높다. 주 지표의 실행 간 흔들림은 같은 설정으로 다시 재야 알 수 있다. |
| 〃 | ③ 고르는 양이 줄었나 | 2차에서 근거를 고른 대비 줄 A 12 / B 16 / C 11 / C-judge 15, 고른 근거 조각 A 177 / B 185 / C 153 / C-judge 173 (예측 파일 건수) | 양은 비슷. 차이는 "어느 조각을 골랐나" |
| 〃 | ④ C는 대부분 포기 | C give_up 41/52 (0.79), 낸 문단 ID 14개. C-judge give_up 39/58, limit_reached 4 | C는 다시 찾기 몫이 작음 (검색은 넓어짐: search_recall 0.612 > A 0.600) |
| 〃 | ⑤ 정답 문단이 검색에는 들었는데 안 고름 | search_recall_rechecked A 0.894 / B 0.875 / C 0.885 / C-judge 0.895 (거의 같음) | 찾기보다 고르기(compare) 쪽 문제. 어느 줄에서 갈렸는지는 줄별 대조가 필요 → 남은 것 |
| C의 F4 direction_top1 (0.230, A 0.312) | ① 흔들림 + 앞 단계 영향 | 11/23 새벽 같은 설정 0.306, 오늘 A 0.312·B 0.305·C-judge 0.320 | C만 낮음. 1회라 원인 모름 → 남은 것 |

남은 것: 다시 찾은 15줄을 판마다 줄별로 대조해 "검색에 든 정답 조각을 compare가 왜 안 골랐나" 보기, 판마다 2회(판정용), 노이즈 범위(cite-idx-v4가 이 DB에 없음).

## 실행
- 예측: `uv run --directory <워크트리> python <work>/overnight_1123_recheck/run_recheck.py <out> --arm c-judge --cache-dir <판 캐시> --workers 4` (git 밖 일회용, run_case fixed_order F1→F4, F3 `use_examiner_paragraphs: false`)
- F3 채점: `uv run python eval/run_eval.py --config experiments/m3-i2-recheck-c-judge/config.yaml --predictions <out>/f3 --rechecked-rows-from <판 A out>/f3`
- F4 채점: `uv run python eval/run_eval.py --config <work의 f4_c-judge.yaml> --predictions <out>/f4 --scores-dir <work>` (F4 점수는 git 밖, 표에만)
