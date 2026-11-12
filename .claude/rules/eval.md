---
paths:
  - "eval/**"
  - "experiments/**"
---
# 채점·실험 규칙 (eval/, experiments/ 파일을 다룰 때만 읽힘)
- 평가 세트는 `goldsets/tune/`(조정용, 봐도 됨)과 `goldsets/report/`(보고용, 발표 점수에만)로 나눈다. 프롬프트·설정을 고치는 동안 `report/`의 답을 열어 보지 않는다.
- 평가 세트를 바꾸면 버전을 올리고(`goldsets/VERSION`), 바꾼 이유를 커밋 본문에 쓴다. 버전이 다른 점수끼리 비교하지 않는다.
- `scores.json`에는 점수, 실패 유형 개수, 토큰·비용·외부 API 호출 수, 평가 세트 버전, 커밋 해시를 스크립트가 넣는다.
- `experiments/index.md`는 `eval/make_index.py`가 만든다. 손으로 고치지 않는다.
- 채점용 모델 호출도 모델 호출 모듈(한 곳)을 거친다 (비용 기록이 한곳에 모이게).
