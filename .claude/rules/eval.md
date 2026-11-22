---
paths:
  - "eval/**"
  - "experiments/**"
---
# 채점·실험 규칙 (eval/, experiments/ 파일을 다룰 때만 읽힘)
- 평가 세트(정답)는 git 밖 `data/goldsets/`에 둔다. `data/goldsets/tune/`(조정용, 봐도 됨)과 `data/goldsets/report/`(보고용, 발표 점수에만)로 나눈다. 프롬프트·설정을 고치는 동안 `report/`의 답을 열어 보지 않는다.
- 평가 세트를 바꾸면 버전을 올리고(`data/goldsets/VERSION`), 바꾼 이유를 커밋 본문에 쓴다. 버전이 다른 점수끼리 비교하지 않는다.
- `scores.json`에는 점수, 실패 유형 개수, 토큰·비용·외부 API 호출 수, 평가 세트 버전, 커밋 해시를 스크립트가 넣는다.
- `experiments/index.md`는 `eval/make_index.py`가 만든다. 손으로 고치지 않는다.
- 모델 출력이 바뀌는 비교(설정 비교·구현 비교 모두. 모델·effort·프롬프트·`impl`)는 같은 설정을 2회 이상 돌려, 같은 설정끼리의 흔들림 폭과 함께 적는다. temperature를 고정할 수 없어 1회 차이는 흔들림 안일 수 있다 (예: `experiments/m1-i3-f1-effort-low-stream64k/card.md` low 0.625 대 medium 0.626, 같은 설정 2회 차이 0.06~0.08).
- 채점용 모델 호출도 모델 호출 모듈(한 곳)을 거친다 (비용 기록이 한곳에 모이게).
