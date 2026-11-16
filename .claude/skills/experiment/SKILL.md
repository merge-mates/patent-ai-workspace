---
name: experiment
description: 비교 실험 하나를 채점하고 실험 카드를 채운다. AI 기능의 점수를 낼 때, 설정 값 하나나 각자 구현을 바꿔 비교할 때 쓴다. 평가 세트를 만들거나 고칠 때는 쓰지 않는다.
argument-hint: "<실험 이름 예: m1-i3-<기능>-<바꾼 것>>"
---

# 실험: $ARGUMENTS

## 시작 전 (사람 확인)
0. **준비물 확인**: 아래 중 하나라도 없으면 돌리지 않고 멈춰서, 무엇이 없는지와 어디서 만드는지(design.md 5-1)를 말한다.
   - 평가 세트와 버전 (`eval/goldsets/<tune|report>/`, `eval/goldsets/VERSION`)
   - 지표와 문턱 (그 기능 design.md 5-1)
   - 채점 스크립트 `eval/run_eval.py` (프레임워크를 정한 뒤 생김), 목록 스크립트 `eval/make_index.py`
   - 기준선 실험 (`card.md`의 기준선이 가리키는 `scores.json`). 첫 실험이면 이번 실험이 기준선이라고 card.md에 적는다
1. `experiments/$ARGUMENTS/config.yaml`이 있는지. 없으면 `experiments/_template/`에서 복사한다. 종류는 둘: **설정 비교**는 `settings`의 값 하나만 기준선과 다르게, **구현 비교**는 `impl`만 다르게 하고 나머지(평가 세트·지표·데이터)는 같게.
2. 기준선이 무엇인지 card.md에 적혀 있는지.
3. 예상 비용·호출 수를 말하고 사람에게 돌릴지 묻는다 (`--dry-run`이 있으면 먼저).

## 돌리기
1. `uv run python eval/run_eval.py --config experiments/$ARGUMENTS/config.yaml`
2. 결과 `scores.json`이 생겼는지, 0개·전부 실패 같은 조용한 실패가 없는지 본다.
3. **experiment-analyst 에이전트**에 넘긴다: scores.json, 기준선 scores.json, 실패 예시 로그 경로(`work/`).
4. card.md를 채운다: 점수 표, 실패 유형 개수, 비용·호출 수, 해석 두세 줄(사람이 고칠 것), 다음 실험 후보.
5. `uv run python eval/make_index.py`로 `experiments/index.md`를 다시 만든다 (손으로 고치지 않는다).

## 규칙
- 앱 코드는 `eval/goldsets/`를 읽지 않는다. 채점기만 읽는다.
- 한 실험에 바꾼 것 하나 (설정 값 하나 또는 impl). 둘 이상 바꿨으면 card에 경고. 구현 비교는 둘 다 같은 평가 세트 버전이어야 한다.
- 답 원문 로그는 `work/`(git 제외). 저장소엔 scores.json과 card.md만.
