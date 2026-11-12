---
name: daily
description: 데일리 스크럼 기록 초안을 git log·PR·이슈·보드에서 모아 쓴다. 매일 데일리 스크럼 전이나 직후에 쓴다. 회의 내용을 지어내지 않고, 사람이 말한 막힌 것·정한 것·이유만 받아 적는다.
argument-hint: "[change]   ← 이터레이션이 바뀌는 날이면 change"
disable-model-invocation: true
---

# 데일리 스크럼 초안 ($ARGUMENTS)

## 모을 것 (마지막 데일리 기록 날짜부터)
0. 시작 날짜: `docs/team/daily/`에서 가장 최근 파일의 날짜. 없으면 7일 전. 주말·쉬는 날 뒤에도 빠짐없이 잡힌다.
1. `git fetch --all` 뒤 `git log --since="<시작 날짜>" --all --format='%an | %h %s'` → 작성자별로 묶는다. 지금 쓰는 사람은 `git config user.name`으로 알고 "나"로 표시한다.
2. `gh pr list --state all --search "updated:>=<시작 날짜>"` → 열림·머지된 PR
3. `gh issue list --label 막힘` → 막힌 이슈
4. 이터레이션이 바뀌는 날(`change`)이면 추가로:
   - 이번 이터레이션 구현 계획(`docs/features/*/tasks.md`의 `## <이터레이션>`)의 task별 상태
   - `experiments/index.md`에서 이번 이터레이션 실험 점수·비용
5. 지난 기록에서 "다음으로" 넘긴 것

## 쓰기
- `docs/team/daily-template.md` 모양으로 `docs/team/daily/YYYY-MM-DD.md` 초안을 쓴다.
- "된 것"은 커밋·PR에서 채운다. **막힌 것, 정한 것, 고른 이유는 비워 두고** 사람에게 한 줄씩 묻는다 (diff에는 이유가 없다).
- 보통 날은 "막힌 것·정한 것"만 남긴다. 없으면 "없음". 표를 억지로 채우지 않는다.
- 이터레이션이 바뀌는 날은 비교 결과, 고른 것과 이유, 다음 이터레이션 목표, 데모 한 줄을 꼭 채운다.

## 하지 않는 것
- 사람이 말하지 않은 결정·이유를 지어내지 않는다.
- 원본 데이터·비공개 샘플·답 원문은 기록에 옮기지 않는다.
