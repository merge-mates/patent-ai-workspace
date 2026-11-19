---
name: start
description: GitHub 이슈 하나를 시작한다. 최신 main에서 팀 규칙 이름으로 브랜치를 만들고, 기본은 `../wt/<브랜치>` worktree에서 일한다 (`--here`면 지금 폴더). 진행 보드 카드를 In Progress로 옮긴다. 이슈 일을 시작할 때 (구현이든 문서든) 먼저 쓴다.
argument-hint: "<이슈번호> [-<사람>] [--here]"
---

# 이슈 시작: #$0

1. `gh issue view $0 --json number,title,state,milestone,labels,body`로 이슈를 읽는다. 닫혀 있으면 멈추고 사람에게 묻는다.
2. 본문의 `먼저 끝나야 할 것`에 적힌 이슈(#번호)가 닫혔는지 `gh issue view <번호> --json state`로 본다. 열린 것이 있으면 목록을 보여 주고 그래도 시작할지 묻는다.
3. `--here`일 때만 지금 폴더의 `git status`가 깨끗한지 본다. 커밋 안 한 변경이 있으면 멈추고 묻는다. 기본(worktree)은 지금 폴더를 바꾸지 않으므로 보지 않는다.
4. 브랜치 이름을 정한다: `<type>/$0-<짧은설명>`. type은 이슈 제목 맨 앞(`feat` `fix` `docs` `chore` …), 짧은설명은 제목을 영어 소문자·하이픈 2~4단어로. 둘이 같은 기능을 각자 구현할 때만 끝에 `-<사람>` (두 번째 인자).
5. 최신 main에서 만든다. 세션마다 폴더를 따로 쓰려고 기본은 worktree다 (세션 둘이 한 폴더에서 `git switch`하면 서로의 브랜치·파일을 바꿔 버린다, 이슈 #94).
   - **기본**: 본 작업 트리 바로 옆 `../wt/<브랜치>`에 worktree를 만들고 그 폴더로 옮겨서 일한다 (예: 본 작업 트리가 `patent_ai/repo/`면 `patent_ai/wt/<브랜치>`). 다른 worktree 안에서 불러도 같은 자리에 만들도록 본 작업 트리 경로를 먼저 구한다.
     ```
     MAIN=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")
     WT="$MAIN/../wt/<브랜치>"
     git fetch origin main
     git worktree add -b <브랜치> "$WT" origin/main
     git -C "$WT" branch --unset-upstream
     ```
     셸 변수(`MAIN`·`WT`)는 다음 명령에 남지 않는다. 처음 구한 값을 절대 경로로 사람에게 보여 주고, 뒤 단계(준비·정리)에서는 그 절대 경로를 그대로 쓴다.
     만든 뒤(또는 이미 있던 worktree면 바로), **`cd` 없이 곧바로 EnterWorktree 도구에 `path: <WT 절대 경로>`를 넘겨 세션을 그 폴더로 옮긴다.** 먼저 `cd`하면 세션에 따라(상위 폴더가 추가 작업 폴더인 앱 세션) 작업 폴더가 먼저 옮겨져 EnterWorktree가 "is the current working directory"로 거절한다. 그 거절이면 이미 옮겨진 것이니 건너뛴다.
     옮긴 뒤 `pwd`와 `git branch --show-current`가 그 worktree·브랜치인지 본다. 아니면 멈추고 사람에게 알린다 (원래 폴더에서 고치지 않게). 이후 읽기·고치기·테스트·커밋은 모두 그 폴더에서 한다. 옮긴 뒤에는 원래 폴더에 git 명령을 쓸 수 없다 ("worktree-isolated session"으로 거절). 원래 폴더가 필요한 확인(`git worktree list`, MAIN·WT 구하기, 원래 폴더 브랜치)은 EnterWorktree 전에 끝낸다.
     `--unset-upstream`은 새 브랜치가 `origin/main`을 따라가지 않게 한다 (그대로 두면 인자 없는 `git push`가 main을 가리킨다). 첫 push는 `/pr-draft`의 `git push -u origin <브랜치>`로 한다.
     - 같은 이름 브랜치에 worktree가 이미 있으면 (`git worktree list`에 그 브랜치) 새로 만들지 않고 그 폴더로 옮긴다.
     - 브랜치만 있고 worktree가 없으면 `git worktree add "$WT" <브랜치>`로 붙인다 (`-b` 없이).
     - 브랜치가 다른 폴더에서 이미 checkout돼 있으면 git이 막는다. 그 폴더로 옮기거나 사람에게 묻는다.
   - **`--here`**: worktree 없이 지금 폴더에서 한다 (예전 동작).
     ```
     git fetch origin main
     git switch -c <브랜치> origin/main
     ```
     이미 같은 이름 브랜치가 있으면 `git switch <브랜치>`로 이어서 한다.
   - 어느 쪽이든 같은 이슈의 다음 계획이면 새 브랜치를 만들고 짧은설명에 계획 이름을 넣는다 (예: `feat/65-m2-i2-db-dump`). 보드는 아래 6번에서 직접 옮긴다.
   - 새 worktree 준비 (기본일 때):
     - `data/`: git 밖이라 worktree에 없다. 원래 폴더 것을 링크한다 (복사하지 않는다): `ln -s <MAIN 절대 경로>/data <WT 절대 경로>/data`. 링크는 `.gitignore`의 `/data`에 걸려 git에 안 잡힌다 (커밋 전 `git status`로 한 번 본다). 채점·색인처럼 `data/`를 읽는 명령이 그래야 돈다.
     - 파이썬: `uv sync --directory <WT 절대 경로>`. 화면 일이면 `npm ci --prefix <WT 절대 경로>/web`. (준비 명령은 지금 폴더가 어디든 같게 돌도록 절대 경로로 쓴다)
     - `.env`: Claude는 읽지도 복사하지도 않는다. 사람에게 "원래 폴더의 `.env`를 이 worktree로 복사하거나 링크하세요 (`ln -s <원래 폴더>/.env .env`)"라고만 알린다.
     - DB: `make db`·`make up`(docker compose)은 원래 폴더 하나에서만 띄우고 모든 worktree가 그 DB를 같이 쓴다. worktree마다 띄우면 Postgres가 여럿 뜨고 포트(5432)가 겹친다. 그 브랜치의 마이그레이션은 worktree에서 `uv run alembic upgrade head`로 공유 DB에 들어가니, 마이그레이션을 고치는 이슈면 먼저 사람에게 알린다.
6. 브랜치를 만들었거나 이어서 하면 늘 보드 카드를 **In Progress**로 옮긴다: `.claude/scripts/board-status.sh $0 "In Progress"`. 출력("보드: #$0 → In Progress")을 사람에게 보여 준다. 실패하면 이유를 사람에게 그대로 전한다 (예: project 권한 없음 → `gh auth refresh -s project`). 훅은 쓰지 않는다 (명령 글자로 이슈를 짐작하다 엉뚱한 카드를 옮겨서 뺐다, 이슈 #83).
7. 다음 할 일을 한 줄로 알린다 (worktree면 일할 폴더 경로도 같이). 셋 중 하나:
   - 이슈에 구현 계획(tasks.md 이슈 계획 링크)이 있으면 `/implement <tasks.md> <이터레이션>`.
   - **작은 이슈**(본문 `구현 계획` 칸이 비어 있고, task 체크리스트와 `확인 명령`이 있음)면 `/implement $0`. 체크리스트나 확인 명령이 없으면 "이슈 본문에 task 체크리스트와 확인 명령 한 줄을 넣어 주세요"라고 묻는다 (CLAUDE.md 일하는 순서 1번: 그 둘이 구현 계획이다).
   - 문서 이슈면 그 문서를 쓰고 `/pr-draft`.
8. 정리: `.claude/`(스킬·설정)는 세션을 연 폴더 것을 읽는다. 이 브랜치에서 `.claude/`를 고쳐도 지금 세션엔 안 들어간다 (머지 → 원래 폴더 `git pull` → 새 세션). PR이 머지되면 사람에게 worktree를 지우라고 안내한다: `git worktree remove "$WT"` 뒤 `git branch -d <브랜치>`. Claude는 지우지 않는다 (지우기는 사람이 요청할 때만). 커밋 안 한 변경이 있으면 git이 막으니 먼저 확인한다.

## 하지 않는 것
- main에서 바로 일하지 않는다. 기본(worktree)일 때 원래 폴더의 브랜치·파일은 건드리지 않는다. 남의 브랜치를 이어받지 않는다 (같은 이슈를 다른 사람이 시작했으면 멈추고 묻는다: 보드에서 In Progress이고 담당자가 다른 사람이면).
- 담당자를 마음대로 바꾸지 않는다. 담당자가 비어 있으면 "나를 담당자로 넣을까요?"만 묻는다 (`gh issue edit $0 --add-assignee @me`).
