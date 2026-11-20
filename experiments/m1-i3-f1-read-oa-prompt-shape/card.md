---
실험: m1-i3-f1-read-oa-prompt-shape
기능: F1
담당: 재아
날짜: 2026-11-21
기준선: experiments/m1-i3-f1-stream-64k/
평가 세트: tune/f1 10건 (VERSION 2)
바꾼 것: `prompts/f1/read_oa.md`에 모양 규칙 3줄 (no_location은 객체, clarity_reason만 문자열, JSON 객체 하나로 끝냄·없는 키 금지)
주 지표: field_accuracy
---
# F1 read_oa 프롬프트: 두 칸의 모양과 JSON 끝 규칙 (이슈 #172 T4)

**가설**: 기준선의 실패 호출 표([m1-i3-f1-stream-64k](../m1-i3-f1-stream-64k/card.md))에서 한도 아래 실패 6회 중 5회가 `no_location`을 문자열로, `clarity_reason`을 객체로 준 것이었다. 프롬프트가 두 칸의 모양을 알려 주지 않았기 때문이다. 모양을 적어 주면 이 오류가 없어진다.
**종류**: 프롬프트 비교
**바꾼 것 (하나)**: 프롬프트 3줄 (sha256 앞 12자 `f86da6d01b6b` → `d680efd54818`, 커밋 6b87e06). 전송층·max_tokens 64000·effort medium은 기준선과 같다.
- 2회 돌렸다. 이 두 실행은 effort 비교([m1-i3-f1-effort-low-stream64k](../m1-i3-f1-effort-low-stream64k/card.md))의 medium 1·2회차와 같은 실행이다 (T4만을 위한 실행을 따로 하지 않았다: 진짜 실행 횟수가 정해져 있었음).
- scores.json은 1회차, 2회차는 git 밖 `work/overnight_1120/f1/a4_medium2_scores.json`. case10은 OA PDF가 없어 예측 없음 0점.

## 결과
| 지표 | 기준선 1회 / 2회 (평균) | 1회 | 2회 | 평균 |
|---|---|---|---|---|
| field_accuracy (주 지표) | 0.600 / 0.675 (0.637) | 0.586 | 0.665 | 0.626 |
| claim_rows | 0.511 / 0.589 | 0.393 | 0.544 | 0.469 |
| location_recall | 0.408 / 0.430 | 0.334 | 0.463 | 0.399 |
| 지어낸 값 / 확인 안 한 원문 위치 | 0 / 0 | 0 / 0 | 0 / 0 | |
| 예측 없음 (case10 PDF 없음 포함) | 2 / 1 | 1 | 1 | |
| 실패 호출 (출력 검사 실패) | 3 / 3 | 3 | 0 | |
| 그중 `no_location` 문자열·`clarity_reason` 객체 | 5 (6회 중) | 0 | 0 | |
| 그중 JSON 뒤에 글자가 더 있음 | 1 | 3 | 0 | |
| max_tokens에 닿은 호출 | 0 / 0 | 0 | 0 | |
| 외부 API 호출 | 11 / 12 | 12 | 9 | |
| 토큰 (입력 · 출력) | 107,325 · 147,934 / 122,891 · 177,934 | 122,466 · 180,035 | 91,539 · 126,483 | |
| 비용($) [가정] 단가 | 0.085 / 0.101 | 0.102 | 0.072 | |

사건별 정확도와 실패 호출 표는 [effort 카드](../m1-i3-f1-effort-low-stream64k/card.md)의 medium 1·2 칸에 있다.

## 해석 (Claude 초안, 사람이 고칠 것)
- 겨냥한 오류는 없어졌다: `no_location`·`clarity_reason` 모양 오류가 2회 5건 → 2회 0건 (effort low 2회까지 네 실행 0건).
- 주 지표 평균은 0.637 → 0.626으로 같은 수준이다. 같은 설정 2회의 차이(0.08)가 더 커서 이 변경이 점수를 바꿨다고 말할 수 없다.
- "JSON 객체 뒤에 글자가 더 있음"은 남았다 (1회차 3회). 규칙 한 줄로는 안 없어졌고 원인은 모른다 (effort 카드 `남은 것`).
- 채택 여부(판단): 채택 쪽. 겨냥한 실패가 없어졌고 점수·안전선(지어낸 값 0)은 그대로다. 정하는 것은 사람.

## 다시 내는 법
- 실행: `uv run python ~/Desktop/project/patent_ai/repo/work/overnight_1120/f1_run.py <out> --effort medium` (git 밖, 캐시 끔, 6b87e06에서)
- 채점: `uv run python eval/run_eval.py --config experiments/m1-i3-f1-read-oa-prompt-shape/config.yaml --predictions <out>_pred --pages <out>_pages`
