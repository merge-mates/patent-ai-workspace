---
name: pr-review
description: 상대의 PR을 리뷰 전용 워크트리에서 리뷰하고, 사람 확인 뒤 판정과 지적을 GitHub 리뷰로 올린다. 리뷰 요청을 받았을 때 쓴다. 내 PR 셀프 점검은 /check를 쓴다.
argument-hint: "<PR 번호>"
---

# PR 리뷰: #$ARGUMENTS

1. **리뷰 전용 워크트리**를 만들고 그 안에서 PR 브랜치를 연다 (내 작업 폴더는 건드리지 않는다). 이후 읽기·테스트는 모두 이 폴더에서 한다.
   ```
   git fetch origin
   git worktree add .claude/worktrees/review-$ARGUMENTS origin/main
   cd .claude/worktrees/review-$ARGUMENTS && gh pr checkout $ARGUMENTS
   ```
2. `gh pr view $ARGUMENTS --json title,body,files,closingIssuesReferences`로 PR 본문과 연결된 이슈·구현 계획을 찾는다.
3. **PR 본문 점검** (이 세션이 직접. code-reviewer에게는 본문을 넘기지 않는다): 본문의 합격 기준 표가 구현 계획의 합격 기준과 맞나, 템플릿 칸이 비었나, 본문의 주장(테스트 통과, 계획과 다르게 한 곳)이 실제 diff와 맞나.
4. **code-reviewer 에이전트**(이슈 모드)에 넘긴다: 구현 계획의 그 이슈 계획, requirements 합격 기준, 바뀐 파일.
5. 코드 지적과 본문 지적을 합쳐 루트 CLAUDE.md의 심각도 순(막음 → 고칠 것 → 참고)으로 정리한다. 지적마다 파일:줄, 재현 방법.
6. **판정을 제안한다**: 막음이 하나라도 있으면 `REQUEST_CHANGES`(수정 요청), 고칠 것만 있으면 `COMMENT`(코멘트), 막음·고칠 것이 없을 때만 `APPROVE`(승인). 고칠 것이 있으면 "승인"이나 "고치면 승인"이라고 말하지 않는다. 재리뷰에서는 담당자 답글을 먼저 읽고, 고칠 것마다 고쳐졌나 / 반박 이유가 맞나 / 이슈로 넘겼나(PR 본문에 링크)를 사람에게 보여 준다. 남은 고칠 것이 없으면 `APPROVE`. 판정과 올릴 지적 목록을 사람에게 보여 준다.
7. 사람이 판정과 지적을 고르거나 고친 뒤 "올려"라고 하면 그대로 **GitHub 리뷰 하나로** 제출한다. 사람 확인 없이 제출하지 않는다. 바뀐 줄의 지적은 줄 댓글, diff 밖 줄·PR 본문에 대한 지적은 리뷰 댓글 본문에 쓴다. 첫머리에 심각도: `막음:` / `고칠 것:` / `참고:` (Conventional Comments 방식).
   ```
   gh api repos/{owner}/{repo}/pulls/$ARGUMENTS/reviews -X POST --input work/review-$ARGUMENTS.json
   # json: {"event":"APPROVE, COMMENT 또는 REQUEST_CHANGES","body":"판정 이유 한두 줄 + diff 밖 지적","comments":[{"path":"<파일>","line":<줄>,"body":"막음: ..."}]}
   ```
   승인은 "머지해도 된다"는 뜻이고 리뷰를 올린 사람 계정의 승인으로 기록된다. Slack 알림은 이 리뷰에서 온다.
8. 사람이 "리뷰 끝"이라고 하면 **반드시** 워크트리와 로컬 PR 브랜치를 지운다:
   ```
   cd "$CLAUDE_PROJECT_DIR"
   git worktree remove .claude/worktrees/review-$ARGUMENTS
   git branch -D <PR 브랜치 이름>
   ```

## 하지 않는 것
- 코드를 고치지 않는다. 상대 브랜치에 커밋·푸시하지 않는다. 상대의 PR 본문을 고치지 않는다.
- 재리뷰는 막음·고칠 것이 있었을 때만, 바뀐 부분과 반박만, 최대 2회.
