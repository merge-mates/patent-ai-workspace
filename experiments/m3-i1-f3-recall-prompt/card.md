---
실험: m3-i1-f3-recall-prompt
기능: F3
담당: 재아
날짜: 2026-11-22
기준선: experiments/m3-i1-f3-independent-first/
평가 세트: tune 10건 (VERSION 2. 기준선과 같음)
바꾼 것: `compare_variant`: standard → recall (대비 프롬프트 prompts/f3/compare.md → prompts/f3/compare_recall.md)
주 지표: selected_recall
---
# F3 대비 프롬프트: 맞는 문단을 모두 고르게 (이슈 #30)

**가설**: 대비 프롬프트가 구성요소마다 후보 문단을 모두 읽고 맞는 문단을 전부 고르게 하면, 검색은 덮었는데 모델이 근거로 고르지 않은 정답 문단(search_recall 0.62 대비 selected_recall 0.18)이 더 근거로 실려 selected_recall이 오른다.
**종류**: 설정 비교 (`config/f3.yaml` `compare_variant`)
**바꾼 것 (하나)**: `compare_variant`: standard → recall. 모델·effort·max_tokens·검색·second_search·출력 모양과 검사는 같다.
**기준선**: `experiments/m3-i1-f3-independent-first/` (실험 세션이 이 브랜치의 부모인 C 브랜치 최종 sha로 `standard` 2회). 같은 코드라 `compare_variant: standard`는 모델에 가는 프롬프트가 바이트까지 같다. 참고로 `experiments/m3-i1-f3-rescore/` (main 9eb8237, 같은 설정 3회, 브랜치 `chore/39-f4-first-score`) selected_recall 0.165 / 0.183 / 0.196 (평균 0.181). 이 값은 #211 앞 코드라 직접 비교하지 않는다. 같은 설정 흔들림 폭은 0.031.
**맞출 조건**: 기준선과 같은 F1 입력 `work/overnight_1120/f1/a3_run2_pred`, `use_examiner_paragraphs: false`, 회차마다 새 캐시, 2회 대 2회.
**오름을 인정할 문턱 (미리 정함)**: recall 2회 selected_recall의 최소 > standard 2회의 최대.
**설정**: 위 조건 + `compare_variant: recall`. 어느 쪽으로 돌았는지는 호출 기록의 단계 이름(`f3.compare_recall` / `f3.compare`)으로 확인한다.
**지킬 선**: "없다고 단정한 문장 0건" (이슈 #30 합격 기준). 못 고르면 판단 보류(unclear)·찾지 못함(difference_candidate)으로만 쓰고 "문헌에 없다"고 단정하지 않는다. 신규성 한 문헌 규칙 위반(novelty_multi_citation)도 0 유지.
**회차마다 같이 볼 것**: 판정 분포(개시됨/차이 후보/불명), 줄당 근거 수, EVIDENCE_REJECTED 줄 수, 종속항 대비 묶음 수·compare 호출 수, 효과 후보 수, "없다고 단정" 0건.
**실행 때 바꿀 줄**: `config/f3.yaml`의 `compare_variant: standard` → `recall` (나머지 그대로. 끝나면 되돌린다).

## 결과 (scores.json에서 스크립트가 채움)
| 지표 | 기준선 | 이번 | 차이 |
|---|---|---|---|
| | | | |
| 비용($) | | | |
| 외부 API 호출 | | | |

## 실패 유형 (개수)
| 유형 | 기준선 | 이번 |
|---|---|---|
| | | |

## 해석 (사람이 두세 줄)

## 해 본 것 / 버린 것

## 다음
