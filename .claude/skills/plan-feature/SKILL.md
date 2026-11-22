---
name: plan-feature
description: 승인된 requirements.md와 design.md로 이번 이터레이션의 tasks.md 이슈 계획을 만든다 (계획 하나 = PR 하나, 이슈 하나에 계획 여러 개 가능). 이터레이션을 시작할 때 쓴다. requirements나 design이 승인 전이면 쓰지 않는다(/interview, /doc-review 먼저).
argument-hint: "<기능> <이터레이션 예: m1-i3>"
---

# 이번 이슈 계획: 기능 $0, $1

## 읽을 것 (이것만)
- `docs/features/$0/requirements.md`, `docs/features/$0/design.md`, (있으면) 지난 `docs/features/$0/tasks.md`
- `docs/architecture.md`, `docs/assumptions.md`, (쓰고 있으면) `docs/api/openapi.yaml`
- 다른 기능 폴더는 읽지 않는다.

## 순서
1. requirements·design에 "승인" 표시(맨 위 `상태: 승인`)가 없으면 멈추고 알린다.
2. `docs/features/$0/tasks.md`가 없으면 `docs/features/_template/tasks.md`에서 만들고, `## $1` 이슈 계획 초안을 아래에 더한다. 지난 계획은 고치지 않는다.
   - task마다: 합격 기준 번호(requirements.md), 고칠 파일, 만들 함수·인터페이스 모양, 테스트할 경우(평소·빈 입력·실패), 확인 방법(끝났다고 볼 명령 한 줄 → 기대 결과), 먼저 끝나야 할 task.
   - 확인 방법 칸은 비우지 않는다. 네트워크·API 키 없이 돌릴 수 있는 명령만 쓴다 (기록된 모델 응답·가짜 응답).
   - task 크기는 루트 CLAUDE.md `진행 단위`를 따른다. task 하나 = 혼자 끝나고 혼자 검증되는 가장 작은 단위(atomic), 목적 하나.
   - task는 2~5개. 하나가 반나절 안쪽. 계획 전체를 PR 하나로 리뷰할 수 있게(400줄 넘으면 나눌지 한 줄 판단).
   - 계획 머리에 "design.md의 어디를 구현하나"와 "맡은 합격 기준 번호"를 적는다 (이슈 점검의 기준).
   - 계획 머리의 mermaid 그림(task 순서)도 채운다. 화살표는 task의 `먼저` 줄과 같게 그린다. 화살표로 이어지지 않은 task는 동시에 할 수 있다.
   - task마다 주인과 고칠 파일을 적어, 둘이 같은 파일을 동시에 고치지 않게 한다. 인터페이스(AI 모듈 입력·출력, API)를 바꾸는 task는 맨 앞에 둔다.
   - AI 동작을 바꾸는 계획이면 "이슈 끝에 점수 한 줄을 어떻게 낼지"(/experiment 명령)를 합격 기준에 넣는다.
3. **plan-reviewer 에이전트**에 초안을 넘긴다. 지적을 반영한다 (다시 보기 최대 2회).
4. 사람에게 보여 준다. 사람이 승인하면 **그 계획 머리**의 `상태: 초안`을 `상태: 승인`으로 바꾼다 (`/implement`가 이 줄을 본다).
5. 승인 뒤, 사람이 "이슈 만들어"라고 하면 계획마다 이슈를 새로 만들지 않는다. 같은 일을 하는 열린 이슈가 있으면 그 이슈에 계획을 붙이고(본문에 계획 링크·task 체크리스트 추가), 없을 때만 새로 만든다. 먼저 같은 일을 하는 이슈가 이미 있는지 `gh issue list --state open --label "기능:<F번호>"`·`--milestone`으로 본다 (마일스톤마다 미리 만든 이슈가 있다). 있으면 새로 만들지 않고 그 이슈의 본문을 계획에 맞게 고친다 (`gh issue edit <번호> --body-file <임시파일>`). 없을 때만 새로 만든다. 새 이슈는 보드에 저절로 붙는다 (Todo). `기능:$0` 라벨이 저장소에 없으면 먼저 만든다 (`.github/labels.md`):
   ```
   gh issue create --title "<type>(<영역>): <계획 목표 한 줄>" --body-file <임시파일> --label <영역> --label "기능:$0" --milestone "<M1 등>" --assignee <주인>
   ```
   본문은 `.github/ISSUE_TEMPLATE/task.md` 칸으로 채우고 구현 계획 링크(`docs/features/$0/tasks.md#$1`)를 넣는다. 만든 이슈 번호를 계획 제목 옆에 적는다.

## 하지 않는 것
- 코드를 쓰지 않는다. 설계를 바꾸지 않는다 (바꿔야 하면 design.md 변경을 제안하고 멈춘다).
