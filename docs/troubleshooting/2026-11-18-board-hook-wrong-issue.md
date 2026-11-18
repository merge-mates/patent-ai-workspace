---
날짜: 2026-11-18
겪은 사람: 재아
관련: 이슈 #80 (PR #81), 이슈 #83
---
# 진행 보드 훅이 엉뚱한 이슈 카드를 옮김 (닫힌 이슈 #8이 In Review로)

**증상**: worktree 세션에서 PR #79(브랜치 `chore/12-code-skeleton-dev-env`)를 만들었는데, 이슈 #12가 아니라 이미 닫힌 이슈 #8 카드가 In Review로 갔다. 그 뒤에도 PR을 만들지 않았는데 #8이 세 번 더 In Review로 갔다.

**원인**: 옛 PostToolUse 훅 `board-sync.sh`가 이슈 번호를 짐작하다 틀렸다.
1. 훅은 `$CLAUDE_PROJECT_DIR`, 곧 메인 체크아웃의 파일로, 메인 체크아웃 폴더에서 돈다. worktree로 옮겨도 이 값은 시작한 루트에 그대로다 (Claude Code hooks 공식 문서). 그래서 `git branch --show-current`가 메인 체크아웃 브랜치(`docs/8-api-spec`)를 돌려줬다. 이건 이슈 #80에서 입력 JSON의 `cwd`를 쓰게 고쳤다.
2. 명령 문자열 어디에든 PR 생성 명령 글자가 있으면 걸렸다. heredoc·echo·grep 안의 글자도 마찬가지다.
3. 확인용 `gh pr view <브랜치>`가 머지된 PR도 찾아 줘서(`docs/8-api-spec` → PR #62 MERGED) 막지 못했다.
4. 훅 파일을 고쳐도 메인 체크아웃이 main을 받기 전까지는 옛 파일이 돈다.

**해결**: 훅을 없앴다 (이슈 #83). `/start`와 `/pr-draft`는 이슈 번호를 이미 알고 있으니, 6번 단계에서 `.claude/scripts/board-status.sh <번호> "<칸>"`를 늘 직접 부른다. 잘못 옮겨진 카드는 `.claude/scripts/board-status.sh <번호> "Done"`으로 되돌린다.

**다시 안 생기게**
- 스킬 없이 손으로 브랜치·PR을 만들었으면 카드도 `board-status.sh`로 손으로 옮긴다.
- `.claude/` 아래 훅·설정을 고쳤으면, 머지 뒤 메인 체크아웃이 main을 받아야 worktree 세션에도 적용된다.
