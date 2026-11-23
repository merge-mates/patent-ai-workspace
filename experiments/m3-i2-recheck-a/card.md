---
실험: m3-i2-recheck-a
기능: 근거 다시 찾기 (F3 (가) 인용문헌 다시 찾기, 이슈 #309)
담당: 재아
날짜: 2026-11-23
기준선: experiments/m3-i2-recheck-a/ (같은 커밋 e8076d2의 판 A)
평가 세트: tune 10건 (VERSION 2). F3 채점은 검색 정답이 있는 8건
바꾼 것: 없음 (기준선: `recheck: none` = 지금 second_search)
주 지표: selected_recall_rechecked
---

> 주 지표 = 1차에 못 찾은 구성요소가 있는 정답 줄의 selected_recall (분모는 판 A 예측의 2차 기록으로 고정, n=15).
> **smoke 1회다.** eval 규칙의 "같은 설정 2회 이상"을 채우지 않았다. 판정(design.md 7-3)은 두 사람 환경을 맞춘 뒤 판마다 2회로 한다. 이 카드의 숫자로 C를 쓸지 정하지 않는다 (밤 작업, 재아 아침 확인 전).

## 결과 (smoke 1회, 실행·채점 커밋 e8076d2, 11/23 10:00~10:25 한 맥에서 판 넷 동시)
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

## 원인 표
판 B·C 카드에 (기준선이라 이 판에는 없음).

## 실행
- 예측: `uv run --directory <워크트리> python <work>/overnight_1123_recheck/run_recheck.py <out> --arm a --cache-dir <판 캐시> --workers 4` (git 밖 일회용, run_case fixed_order F1→F4, F3 `use_examiner_paragraphs: false`)
- F3 채점: `uv run python eval/run_eval.py --config experiments/m3-i2-recheck-a/config.yaml --predictions <out>/f3 --rechecked-rows-from <판 A out>/f3`
- F4 채점: `uv run python eval/run_eval.py --config <work의 f4_a.yaml> --predictions <out>/f4 --scores-dir <work>` (F4 점수는 git 밖, 표에만)
