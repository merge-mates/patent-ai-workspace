---
name: pr-draft
description: 지금 브랜치의 PR 제목과 본문 초안을 팀 틀에 맞춰 만들고, 사람이 OK하면 push와 PR 생성까지 한다. 구현과 /check가 끝난 뒤 쓴다.
---

# PR 초안

1. `git log main..HEAD --oneline`, `git diff main...HEAD --stat`, 브랜치 이름(`<type>/<이슈번호>-…`)에서 이슈 번호 N을 찾는다. 번호가 없으면 멈추고 어느 이슈인지 묻는다 (이슈 없는 PR은 보드에 안 잡힌다).
2. 제목: 커밋 규칙과 같은 모양 `<type>(<영역>): <한 줄>` (머지하면 이 제목이 main의 merge commit 제목이 된다). 70자 이하.
3. 본문: `.github/pull_request_template.md`의 칸을 채운다. `Closes #` 줄은 `Closes #N` 또는 `Refs #N`으로 채운다. 이슈의 남은 계획(이슈 본문 체크리스트·tasks.md)이 이 PR로 다 끝나면 `Closes #N`(머지하면 이슈가 닫히고 보드 카드가 Done으로 간다), 남은 계획이 있으면 `Refs #N`. 어느 쪽인지 초안에 이유를 한 줄 적는다. 빈 `Closes #`로 두지 않는다. diff가 400줄을 넘으면 `## 무엇을` 아래에 커밋별 리뷰 순서(커밋 제목 목록)를 적는다. 직전 /implement·/check 결과가 있으면 그대로 쓴다. 없는 칸은 비워 두고 "없음"이라고 쓴다.
4. `work/pr-draft.md`에 저장하고 제목·본문을 사람에게 보여 준다.
5. push와 PR 생성은 매번 사람이 승인한다 (확인 창). 사람이 초안을 보고 OK하면 Claude가 push하고 PR을 만든다. 사람 OK 없이 push하지 않는다. main에는 push하지 않는다.
   ```
   git push -u origin <브랜치>
   gh pr create --title "<제목>" --body-file work/pr-draft.md --assignee @me
   ```
6. `Closes #N` PR을 만들면 늘 이슈 #N 카드를 **In Review**로 옮긴다 (`Refs #N` PR이면 남은 계획이 있으니 카드는 In Progress 그대로 둔다): `.claude/scripts/board-status.sh N "In Review"`. 출력("보드: #N → In Review")을 사람에게 보여 주고, 실패하면 이유를 사람에게 전한다.
7. worktree에서 일했으면(`git rev-parse --git-dir`이 `.git/worktrees/` 아래) 정리 명령을 한 줄 알린다: "머지 뒤 원래 폴더에서 `git worktree remove ../wt/<이슈번호>-<짧은설명>` → `git branch -d <브랜치>`". 머지 전에는 지우지 않는다 (리뷰 고침을 이 폴더에서 한다). Claude는 지우지 않는다.
