---
실험: m1-i3-f1-stream-64k
기능: F1
담당: 재아
날짜: 2026-11-21
기준선: experiments/m1-i3-f1-read-oa-prompt-hint/
평가 세트: tune/f1 10건 (VERSION 2)
바꾼 것: 전송층 스트리밍 + `settings.max_tokens`: 16000 → 64000
주 지표: field_accuracy
---
# F1 read_oa 스트리밍 + max_tokens 64000, 2회 (이슈 #172 T3)

**가설**: 예측 없음의 큰 몫은 출력이 16000에서 잘리는 것이다. 스트리밍으로 바꾸고 상한을 64000으로 올리면 잘림이 없어지고, 남는 실패는 stop_reason과 검사 오류로 원인을 가를 수 있다.
**종류**: 설정 비교 (전송 방식과 상한은 함께 바뀜: SDK가 큰 max_tokens를 스트리밍에서만 받음)
**바꾼 것**: `AnthropicTransport`를 `messages.stream` + `get_final_message`로, `config/f1.yaml` `max_tokens` 64000. 프롬프트(sha256 앞 12자 `f86da6d01b6b`)·모델·effort는 기준선과 같다.
- 2회 돌렸다(11/21 새벽). scores.json은 1회차, 2회차는 git 밖 `work/overnight_1120/f1/a3_run2_scores.json`.
- 이 Mac에는 tune 10건 중 case10의 OA PDF가 없어 9건만 돌렸다. case10은 예측 없음 0점으로 들어간다.

## 결과
| 지표 | 기준선 (16000, 1회) | 1회 | 2회 | 2회 평균 |
|---|---|---|---|---|
| field_accuracy (주 지표, 10건) | 0.441 | 0.600 | 0.675 | 0.637 |
| field_accuracy_micro | 0.356 | 0.613 | 0.705 | 0.659 |
| basic | 0.700 | 0.800 | 0.900 | 0.850 |
| rejections | 0.579 | 0.737 | 0.895 | 0.816 |
| citations | 0.844 | 0.906 | 0.969 | 0.938 |
| claim_rows | 0.175 | 0.511 | 0.589 | 0.550 |
| location_recall / location_exact | 0.063 / 0.063 | 0.408 / 0.353 | 0.430 / 0.428 | 0.419 / 0.391 |
| 지어낸 값 (fabricated_values) | 0 | 0 | 0 | |
| 확인 안 한 원문 위치 | 0 | 0 | 0 | |
| 예측 없음 (case10 PDF 없음 포함) | 3 | 2 | 1 | |
| 그중 출력 검사 2번 실패 | 2 (case2·case5) | 1 (case5) | 0 | |
| 외부 API 호출 | 14 | 11 | 12 | |
| 출력 검사 실패 호출 | 7 | 3 | 3 | |
| max_tokens에 닿은 호출 (stop_reason = max_tokens) | 4 (16000) | 0 | 0 | |
| 한 호출 최대 출력 토큰 | 16,000 (잘림) | 23,807 | 26,944 | |
| 토큰 (입력 · 출력) | 142,704 · 181,919 | 107,325 · 147,934 | 122,891 · 177,934 | |
| 비용($) [가정] 단가 | 약 0.105 | 약 0.085 | 약 0.101 | |

- 비용 셈은 기준선 카드와 같다 ([가정] Haiku 5.5 $0.10/$0.50 per MTok, scores.json `cost`는 채점기 비용 0, #156).

사건별 정확도
| 사건 | 기준선 | 1회 | 2회 |
|---|---|---|---|
| case1 | 0.722 | 0.722 | 0.778 |
| case2 | 없음 | 0.860 | 0.892 |
| case3 | 0.690 | 0.966 | 0.793 |
| case4 | 0.422 | 0.378 | 0.533 |
| case5 | 없음 | 없음 | 0.766 |
| case6 | 1.000 | 1.000 | 1.000 |
| case7 | 0.622 | 0.622 | 0.622 |
| case8 | 0.400 | 0.895 | 0.779 |
| case9 | 0.554 | 0.554 | 0.589 |
| case10 | 없음 (PDF 없음) | 없음 | 없음 |

## 실패 호출 표 (실패한 모델 답을 같은 스키마로 다시 검사, git 밖 `work/overnight_1120/f1/fail_table.py`)
| 실행 | 사건 | 호출 | 출력 토큰 | stop_reason | 검사 오류 | 원인 한 줄 |
|---|---|---|---|---|---|---|
| 기준선 | case1 | 1 | 14,039 | (기록 전) | JSON 아님: Extra data (끝에서 2글자) | JSON 객체가 끝난 뒤 `}` 하나를 더 붙임 |
| 기준선 | case2 | 1·2 | 16,000 · 16,000 | (기록 전) | JSON 아님: 문자열이 안 닫힘 | 16000에서 잘림 |
| 기준선 | case5 | 1 | 16,000 | (기록 전) | JSON 아님: 문자열이 안 닫힘 | 16000에서 잘림 |
| 기준선 | case5 | 2 | 14,846 | (기록 전) | `claim_rows[].no_location` 객체 아님 | 줄 단위 no_location을 문자열로 줌 |
| 기준선 | case8 | 1 | 13,656 | (기록 전) | 모르는 키 `rejection_count_note` | 출력 모양에 없는 키를 만듦 |
| 기준선 | case9 | 1 | 16,000 | (기록 전) | JSON 아님: 문자열이 안 닫힘 | 16000에서 잘림 |
| 1회 | case5 | 1 | 23,807 | end_turn | `claim_rows[].clarity_reason` 문자열 아님 | clarity_reason을 {value, raw_text, page, ambiguous} 객체로 줌 |
| 1회 | case5 | 2 | 18,495 | end_turn | `claim_rows[].no_location` 객체 아님 | 줄 단위 no_location을 문자열로 줌 |
| 1회 | case6 | 1 | 2,940 | end_turn | `claim_rows[].clarity_reason` 문자열 아님 | 위와 같음 |
| 2회 | case1 | 1 | 13,470 | end_turn | JSON 아님: Extra data (끝에서 2글자) | 끝에 `}` 하나를 더 붙임 |
| 2회 | case2 | 1 | 26,944 | end_turn | `claim_rows[].clarity_reason` 문자열 아님 ×2 | 객체로 줌 |
| 2회 | case5 | 1 | 21,996 | end_turn | `claim_rows[].no_location` 객체 아님 | 문자열로 줌 |

원인 표 (고치기 전)
| 칸 | 본 것 | 원인 | 고칠 곳 |
|---|---|---|---|
| 잘림 (기준선 4회) | 64000에서는 0회. 한 호출 최대 26,944 토큰 | 상한 16000이 낮았음 | 이 실험으로 풀림 |
| `no_location` 문자열 (3회, 늘 case5) | 스키마는 Item 객체(`extraction.py` `ClaimRowExtraction.no_location`), 프롬프트 예시는 `null`만 보이고 규칙 문장은 "그 표현 글자를 적습니다" | 프롬프트가 모양을 안 알려 줌 | 프롬프트 (T4) |
| `clarity_reason` 객체 (3회) | 스키마는 문자열, 프롬프트 예시는 `null`, 다른 칸은 다 객체 | 프롬프트가 "이 칸만 문자열"을 안 알려 줌 | 프롬프트 (T4) |
| 끝에 `}` 하나 더 (2회, 늘 case1) | 답 끝 2글자가 남음 | 모름 (긴 중첩 JSON 끝에서 모델이 닫는 괄호를 하나 더 씀. 짐작) | 프롬프트에 "객체 하나로 끝냄" 한 줄만 (T4). 코드로 고쳐 읽지는 않음 |
| 모르는 키 (1회) | `rejection_count_note` | 모델이 출력 모양에 없는 키를 만듦 | 프롬프트에 "없는 키를 만들지 않음" 한 줄 (T4) |
| case4·7·9 정확도 0.4~0.6 | 세 실행 모두 claim_rows가 낮음 | 이 이슈 범위 밖 (예측은 있음) | `남은 것` |

## 해석 (Claude 초안, 사람이 고칠 것)
- 잘림은 없어졌다 (max_tokens에 닿은 호출 4 → 0). 예측 없음도 PDF 없는 case10을 빼면 2 → 1·0건이다.
- 주 지표 2회 평균 0.637은 예측 없음이 줄어든 몫이 크다. 예측이 있는 사건끼리의 차이는 같은 설정의 흔들림 안이다.
- 남은 출력 검사 실패(회마다 3회)는 모두 한도 아래이고 stop_reason이 end_turn이다. 잘림이 아니라 모양 오류다. 원인은 표대로 프롬프트가 두 칸의 모양을 알려 주지 않은 것 → T4에서 프롬프트를 고친다.
- 지어낸 값 0, 확인 안 한 원문 위치 0 유지.
- 채택 여부(판단): 채택 쪽. 호출 하나가 길어지는 것(최대 약 27k 토큰)은 서버가 비동기로 돌려 문제없다(이슈 #172 본문). 정하는 것은 사람.

## 남은 것
- 호출 기록(`CallRecord`·`agent_steps`)에 stop_reason·`output_truncated`를 남기는 것은 DB 마이그레이션이 필요해 이 PR 브랜치에 없다. 로컬 브랜치 `fix/172-f1-no-prediction-call-record`에 따로 있음 (재아 결정 대기). 위 표의 stop_reason은 실행 스크립트가 전송층 답에서 직접 읽어 남긴 것이다.
- case10 OA PDF 없음 (이 Mac).
- case4·case7·case9의 낮은 claim_rows.

## 다시 내는 법
- 실행: `uv run python ~/Desktop/project/patent_ai/repo/work/overnight_1120/f1_run.py <out>` (git 밖, 캐시 끔, 75e12af에서)
- 채점: `uv run python eval/run_eval.py --config experiments/m1-i3-f1-stream-64k/config.yaml --predictions <out>_pred --pages <out>_pages`
