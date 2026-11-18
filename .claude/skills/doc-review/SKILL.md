---
name: doc-review
description: 기획안·requirements·design·architecture 문서를 critic 에이전트와 체크리스트로 검증한다. 문서를 "다 썼다"고 하기 전, 상대에게 승인을 부탁하기 전에 쓴다. 코드 리뷰에는 쓰지 않는다(/pr-review).
argument-hint: "<문서 경로> [plan|requirements|design]"
disable-model-invocation: true
---

# 문서 검토: $ARGUMENTS

## 순서
1. 종류를 정한다: 두 번째 인자, 없으면 파일 이름으로 (`product.md`→plan, `requirements.md`→requirements, `design.md`·`architecture.md`→design).
2. 체크리스트를 읽는다: `${CLAUDE_SKILL_DIR}/references/checklist-<종류>.md`.
3. **critic 에이전트**를 부른다. 넘길 것: 문서 경로, 체크리스트 경로, 이 문서가 기대는 상위 문서(requirements면 product.md, design이면 requirements.md + architecture.md, 쓰고 있으면 api/openapi.yaml).
   - critic은 문서를 고치지 않는다. 판정(통과/보강/다시)과 지적만 낸다.
4. critic 결과와 별개로, 체크리스트 항목을 하나씩 직접 확인해 표로 만든다 (예/아니오/해당 없음 + 근거 줄).
5. 두 결과를 합쳐 아래 모양으로 낸다. 지적마다 심각도(막음/고칠 것/참고)를 루트 CLAUDE.md 기준으로 단다.
6. "보강"이면 사람이 고친 뒤 **바뀐 부분만** 다시 본다. 다시 보기는 최대 2회 (그 뒤엔 사람이 정한다).

## 내놓을 것
```
## 문서 검토: <파일> (<날짜>, <몇 번째>)
판정: 통과 / 보강 / 다시
### 막음
- [절] 무엇이 문제 → 고칠 방향 (근거: 체크리스트 항목 / 상위 문서 줄)
### 고칠 것
### 참고
### 체크리스트 표
| 항목 | 결과 | 근거 |
### 시뮬레이션 (critic)
- "이 문서만 보고 구현자가 만들면 무엇이 달라질 수 있나" 2~3개
```

## 규칙
- 문서를 직접 고치지 않는다. 고칠 문장 제안까지만.
- 출처 없는 숫자는 "[가정]으로 표시할 것"으로 지적한다.
- `[확인 필요]`가 하나라도 남아 있으면 통과시키지 않는다 (판정은 보강 이하). `[가정]`은 모르지만 일단 정한 것이라 남아 있어도 된다.
- requirements는 사용 장면이 없거나, 합격 기준에 상황이 빠졌거나, 기준에 `(필수)`·`(있으면 좋음)` 표시가 없으면 '고칠 것'으로 지적한다.
- design은 9절 `어디서 테스트하나` 줄이 비었으면 '고칠 것'으로 지적한다.
- 결과는 화면에만 낸다. 저장하라고 하면 PR 본문이나 `docs/team/`에 붙인다 (저장소에 검토 기록 파일을 만들지 않는다).
