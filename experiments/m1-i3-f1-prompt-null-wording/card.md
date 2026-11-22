---
실험: m1-i3-f1-prompt-null-wording
기능: F1
담당: 재아
날짜: 2026-11-22
기준선: experiments/m1-i3-f1-read-oa-prompt-shape/
평가 세트: tune/f1 10건 (VERSION 2)
바꾼 것: `prompts/f1/read_oa.md` null·문자열 예외 문구 맞추기 (이슈 #193 task 1, sha256 앞 12자 d680efd54818 → a2d095469fda, 커밋 9d99d3b)
주 지표: field_accuracy
---
# F1 read_oa 프롬프트: null·문자열 예외 문구 맞추기 (이슈 #193)

**가설**: 프롬프트 안의 null 규칙과 "문자열로 쓰는 칸" 예외 문구가 서로 어긋나 있던 것(14·32·58·60·77·78줄)을 맞추면, 모양 오류가 늘지 않고 점수는 같거나 낫다.
**종류**: 프롬프트 비교
**바꾼 것 (하나)**: 프롬프트 문구만. 코드·설정(`config/f1.yaml`: haiku-5-5, effort medium, max_tokens 64000, model_input raw)은 main 9eb8237 그대로.
- 같은 설정 2회 (캐시 끔 스크립트 `work/overnight_1120/f1_run.py`). scores.json은 1회차, 2회차는 git 밖 `work/overnight_1121/runs/score_f1_193_run2/scores.json`. case10은 OA PDF가 없어 예측 없음 0점 (기준선과 같음).
- 기준선(m1-i3-f1-read-oa-prompt-shape)은 fix/172 6b87e06 판에서 돌린 값이다. 그 뒤 main에 들어간 F1 변경(#154 보정 참고사항 값 등)이 있어 코드 판이 다르다. 그래서 **같은 코드 판 비교용으로 main 9eb8237(이 브랜치 직전, 프롬프트 d680efd54818) 1회**도 같이 적는다 (#154 확인용으로 11/22 돌린 실행, git 밖 `work/overnight_1121/runs/score_f1_154/`).

## 결과 (n=10)
| 지표 | 기준선 1회 / 2회 (평균) | main 9eb8237 같은 판 1회 | 이번 1회 | 이번 2회 | 이번 평균 |
|---|---|---|---|---|---|
| field_accuracy (주 지표) | 0.586 / 0.665 (0.626) | 0.578 | 0.674 | 0.598 | **0.636** |
| field_accuracy_micro | | 0.568 | 0.696 | 0.609 | 0.652 |
| basic | | 0.900 | 0.900 | 0.900 | 0.900 |
| rejections | | 0.895 | 0.895 | 0.895 | 0.895 |
| citations | | 0.969 | 0.969 | 0.969 | 0.969 |
| claim_rows | 0.393 / 0.544 | 0.375 | 0.574 | 0.438 | 0.506 |
| location_recall | 0.334 / 0.463 | 0.365 | 0.391 | 0.340 | 0.365 |
| 지어낸 값 / 확인 안 한 원문 위치 | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 | |
| 출력 검사 실패로 다시 부름 | 3 / 0 | 0 | 0 | 1 (다시 불러 통과) | |
| 외부 API 호출 | 12 / 9 | 9 | 9 | 10 | |
| 토큰 (입력 · 출력) | | 91,632 · 129,239 | 93,384 · 133,755 | 103,596 · 140,832 | |
| 비용 ($) | 0.102 / 0.072 | 0.074 | 0.076 | 0.081 | |
- 단가 Haiku 5.5 $0.10/$0.50 per MTok (claude-api 스킬 모델 표 2026-11-03). 이번 2회 합 $0.157.
- 한 줄: tune v2 F1 #193 프롬프트 2회 field_accuracy 0.674·0.598 (평균 0.636, 기준선 평균 0.626, 같은 판 main 1회 0.578), 지어낸 값 0, $0.157.

## 해석 (Claude 초안, 사람이 고칠 것)
- 주 지표 평균 0.636은 기준선 평균 0.626과 같은 수준이다. 같은 설정 2회 차이(0.076)가 기준선과의 차이(+0.010)보다 커서 이 문구 변경이 점수를 바꿨다고 말할 수 없다.
- 움직인 칸은 claim_rows(청구항 줄)뿐이고 흔들림이 크다 (0.438~0.574). basic·rejections·citations는 3 실행 모두 같다.
- 꼭 지킬 선: 지어낸 값 0, 확인 안 한 원문 위치 0 그대로.
- 채택 여부(판단): 채택 쪽. 문구가 서로 어긋나던 것을 맞춘 정리이고 점수·안전선은 그대로다. 정하는 것은 사람.

## 다시 내는 법
- 실행: `uv run python <repo>/work/overnight_1120/f1_run.py <out>` (이 브랜치 worktree에서, git 밖, 캐시 끔)
- 채점: `uv run python eval/run_eval.py --config experiments/m1-i3-f1-prompt-null-wording/config.yaml --predictions <out 예측> --pages <out 쪽 글자>`
