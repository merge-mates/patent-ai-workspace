---
name: pr-draft
description: 지금 브랜치의 PR 제목과 본문 초안을 팀 틀에 맞춰 만들고, 사람이 OK하면 push와 PR 생성까지 한다. 구현과 /check가 끝난 뒤 쓴다.
---

# PR 초안

1. `git log main..HEAD --oneline`, `git diff main...HEAD --stat`, 브랜치 이름에서 이슈 번호를 찾는다.
2. 제목: 커밋 규칙과 같은 모양 `<type>(<영역>): <한 줄>` (squash 머지하면 이 제목이 main의 커밋이 된다). 70자 이하.
3. 본문: `.github/pull_request_template.md`의 칸을 채운다. 직전 /implement·/check 결과가 있으면 그대로 쓴다. 없는 칸은 비워 두고 "없음"이라고 쓴다.
4. `work/pr-draft.md`에 저장하고 제목·본문을 사람에게 보여 준다.
5. push와 PR 생성은 매번 사람이 승인한다 (확인 창). 사람이 초안을 보고 OK하면 Claude가 push하고 PR을 만든다. 사람 OK 없이 push하지 않는다. main에는 push하지 않는다.
   ```
   git push -u origin <브랜치>
   gh pr create --title "<제목>" --body-file work/pr-draft.md --assignee @me
   ```
