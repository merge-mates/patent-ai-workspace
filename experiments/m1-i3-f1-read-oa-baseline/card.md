---
실험: m1-i3-f1-read-oa-baseline
기능: F1
담당: 은진
날짜: 2026-11-19
기준선: experiments/m1-i3-f1-read-oa-baseline/
평가 세트: tune/f1 10건 (VERSION 2)
바꾼 것: 기준선 (처음 정답 대비 채점, 바꾼 것 없음)
주 지표: field_accuracy
---
# F1 read_oa tune 기준선 (이슈 #142)

**가설**: 없음. #23(M1 report 평가) 전에 지금 main의 read_oa가 tune 정답 대비 몇 점인지 처음 잰다.
**종류**: 기준선
**설정**: main 3f72364 그대로. `config/f1.yaml` read_oa (claude-haiku-5-5, max_tokens 16000, max_model_calls 2, model_input raw, PDF 도구 pdfplumber).
- #136(temperature 대신 effort)은 머지 전이라 반영 안 했다. 설정의 `temperature: 0`은 전송층이 SDK에 넘기지 않아 실제로는 기본값으로 불렀다. effort도 정하지 않아 모델 기본값(medium)이다.
- 한 번씩만 돌렸다. 같은 입력에서 답이 흔들리는 크기는 모른다.

## 결과 (scores.json)
| 지표 | 값 |
|---|---|
| field_accuracy (OA 평균, 주 지표) | 0.605 |
| field_accuracy_micro (칸 전체) | 0.528 |
| basic (번호·날짜·통지 종류·청구항·보정 참고) | 0.725 |
| rejections (종류·조문·지원·대상) | 0.789 |
| citations (번호·연결 거절이유) | 0.906 |
| claim_rows (청구항 줄) | 0.384 |
| location_recall / location_exact | 0.305 / 0.276 |
| 지어낸 값 (fabricated_values) | 0 |
| 확인 안 한 원문 위치 (unverified_locations) | 0 |
| 비용($) | 약 0.089 (입력 129,255·출력 151,929 토큰 × [가정] Haiku 5.5 $0.10/$0.50 per MTok. 단가는 Claude Code에 들어 있는 Claude API 안내의 가격 표(11/03 기준)에서 옮김. 저장소엔 출처 없음, `config/f1.yaml`에도 가격 키 없음) |
| 외부 API 호출 | 14 (10건 + 출력 검사 실패 재시도 4) |

- scores.json의 `cost`는 채점기 자신의 비용(0)이다. 위 비용은 read_oa 실행 기록(git 밖 `work/f1_baseline/calls.json`)에서 셈했다.
- 예측이 없는 1건(case5)을 0점으로 넣은 값이다. 나머지 9건 평균은 0.673.

사건별 (이름표는 정답 파일 이름 순서. m1-i3-f1-model-input-tables의 case1~5와 다른 묶음이다. 이름표 ↔ 번호는 git 밖 `work/f1_baseline/labels.json`에만)
| 사건 | 정확도 | basic | rejections | citations | claim_rows | 위치 recall |
|---|---|---|---|---|---|---|
| case1 | 0.759 | 7/8 | 4/4 | 4/4 | 26/38 | 0.33 |
| case2 | 0.376 | 6/8 | 12/12 | 2/2 | 15/71 | 0.19 |
| case3 | 0.828 | 7/8 | 8/8 | 4/4 | 5/9 | 0.50 |
| case4 | 0.511 | 6/8 | 4/4 | 3/4 | 10/29 | 0.12 |
| case5 | 0 (예측 없음) | 0/8 | 0/12 | 0/2 | 0/42 | 0 |
| case6 | 0.733 | 7/8 | 4/4 | - | 0/3 | - |
| case7 | 0.568 | 6/8 | 5/8 | 8/8 | 2/13 | 0.33 |
| case8 | 0.379 | 6/8 | 8/8 | 2/2 | 20/77 | 0.00 |
| case9 | 0.964 | 7/8 | 11/12 | 6/6 | 30/30 | 0.96 |
| case10 | 0.935 | 6/8 | 4/4 | - | 19/19 | - |

## 실패 유형 (개수)
| 유형 | 개수 |
|---|---|
| 예측 없음 (출력 검사 두 번 실패, case5) | 1 |
| 출력 검사 실패 호출 (14회 중) | 5 |
| 그중 출력이 max_tokens 16000에 닿음 | 2 (case2 1차, case5 1차). 그 밖 15,270·14,585 토큰 2회, 7,069 토큰 1회 |
| 위치 채점에서 뺀 줄: 같은 취지만 / 위치 없음 | 17 / 2 |

## 해석 (Claude 초안, 사람이 고칠 것)
- 꼭 지킬 선은 지켰다: 지어낸 값 0, 확인 안 한 원문 위치 0.
- 점수를 끌어내리는 건 청구항 줄(0.384)과 위치(0.305)다. 줄이 많은 사건(case2 71칸, case8 77칸)에서 크게 빠진다. 거절이유·인용은 0.79~0.91로 비교적 낫다.
- 출력 검사 실패는 5회다. 그중 2회(case2·case5 1차)는 max_tokens 16000에서 잘렸고, 3회(15,270·14,585·7,069 토큰)는 한도 아래에서 검사에 걸렸다(원인 미확인). case5 2차 실패도 한도 아래라, max_tokens만 올려서 case5가 산다고 말할 수 없다. 실패 응답의 검사 오류·stop_reason은 아직 안 봤다.
- basic은 거의 모든 사건에서 1~2칸씩 틀린다. 그중 1칸은 모델 품질이 아니라 구조 문제일 수 있다: 보정 참고사항은 `read_oa.py` `_hint_note`가 `compare_by="raw_text"`로 합쳐 `value`가 None이 되고(글자는 raw_text에만), 채점은 `value`끼리 비교한다(`eval/f1/score.py` `_score_basic`). 그러면 보정 참고사항이 있는 OA는 이 칸이 늘 틀린다 (리뷰 #146에서 짚음, F1 쪽 이슈 #154).
- #154 뒤 (main 9eb8237 = 고침 3c8e277 포함, 1회, 11/22): basic 0.725 → 0.900. 다만 이 기준선(main 3f72364) 뒤 다른 F1 변경(프롬프트 모양·effort·스트리밍 등)도 같이 들어간 판이라 #154 몫만 떼어 낸 값이 아니다. 같은 실행 field_accuracy 0.605 → 0.578, rejections 0.789 → 0.895, citations 0.906 → 0.969, claim_rows 0.384 → 0.375, location_recall 0.305 → 0.365, 지어낸 값 0. 9/10건(case10 OA PDF 없음), 비용 $0.074 (Haiku 9회). 예측·채점은 git 밖 `work/overnight_1121/runs/f1_154_pred`·`score_f1_154/`.

## 해 본 것 / 버린 것
- 없음 (기준선).

## 다음
- #136(effort 명시) 머지 뒤 같은 10건으로 다시 재서 이 기준선과 비교 (설정 비교, 바꾼 것 하나).
- 정확도 문턱 (F1 requirements 9번): 이 0.605로는 정하지 않는다. #136과 보정 참고사항 칸을 고친 뒤 tune 10건을 다시 잰 점수로, #23 report 평가 전에 정한다 (11/20 은진 결정, report 점수를 보고 정하지 않음).
- 출력 검사 실패: 실패 응답의 검사 오류·stop_reason부터 확인 → 그 뒤 max_tokens나 청구항 줄 나눠 부르기. case5처럼 통째로 0점이 되는 것부터 막기.
- basic의 보정 참고사항 칸(위 해석)을 고친 뒤 나머지 틀린 칸 찾기. 청구항 줄이 빠지는 유형(줄 없음 / 인용 틀림 / 쪽 틀림) 나눠 세기.
- 채점기 scores.json `cost`에 실행(read_oa) 비용을 넣는 길이 없다. 점수 표의 비용 칸이 $0.00으로 보인다 (#156).
