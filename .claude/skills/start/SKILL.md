---
name: start
description: GitHub 이슈 하나를 시작한다. 최신 main에서 팀 규칙 이름으로 브랜치를 만들고 진행 보드 카드를 In Progress로 옮긴다. 이슈 일을 시작할 때 (구현이든 문서든) 먼저 쓴다.
argument-hint: "<이슈번호> [-<사람>]"
---

# 이슈 시작: #$0

1. `gh issue view $0 --json number,title,state,milestone,labels,body`로 이슈를 읽는다. 닫혀 있으면 멈추고 사람에게 묻는다.
2. 본문의 `먼저 끝나야 할 것`에 적힌 이슈(#번호)가 닫혔는지 `gh issue view <번호> --json state`로 본다. 열린 것이 있으면 목록을 보여 주고 그래도 시작할지 묻는다.
3. `git status`가 깨끗한지 본다. 커밋 안 한 변경이 있으면 멈추고 묻는다.
4. 브랜치 이름을 정한다: `<type>/$0-<짧은설명>`. type은 이슈 제목 맨 앞(`feat` `fix` `docs` `chore` …), 짧은설명은 제목을 영어 소문자·하이픈 2~4단어로. 둘이 같은 기능을 각자 구현할 때만 끝에 `-<사람>` (두 번째 인자).
5. 최신 main에서 만든다:
   ```
   git fetch origin main
   git switch -c <브랜치> origin/main
   ```
   이미 같은 이름 브랜치가 있으면 새로 만들지 않고 `git switch <브랜치>`로 이어서 한다 (보드는 아래 6번에서 직접 옮긴다).
6. 브랜치를 만들었거나 이어서 하면 늘 보드 카드를 **In Progress**로 옮긴다: `.claude/scripts/board-status.sh $0 "In Progress"`. 출력("보드: #$0 → In Progress")을 사람에게 보여 준다. 실패하면 이유를 사람에게 그대로 전한다 (예: project 권한 없음 → `gh auth refresh -s project`). 훅은 쓰지 않는다 (명령 글자로 이슈를 짐작하다 엉뚱한 카드를 옮겨서 뺐다, 이슈 #83).
7. 다음 할 일을 한 줄로 알린다: 이슈에 구현 계획(tasks.md 이슈 계획)이 있으면 `/implement <tasks.md> <이터레이션>`, 문서 이슈면 그 문서를 쓰고 `/pr-draft`.

## 하지 않는 것
- main에서 바로 일하지 않는다. 남의 브랜치를 이어받지 않는다 (같은 이슈를 다른 사람이 시작했으면 멈추고 묻는다: 보드에서 In Progress이고 담당자가 다른 사람이면).
- 담당자를 마음대로 바꾸지 않는다. 담당자가 비어 있으면 "나를 담당자로 넣을까요?"만 묻는다 (`gh issue edit $0 --add-assignee @me`).
