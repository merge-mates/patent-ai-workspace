# 팀원 시작 안내

## 처음 한 번 (클론한 날)
1. `git clone <레포 주소>` → `cd <폴더>` → `claude` 실행. "이 폴더를 신뢰" 질문에 허락한다 (그래야 팀 설정·스킬·훅이 켜진다). `claude`는 늘 **저장소 폴더 안에서** 연다. 상위 폴더에서 열면 팀 설정이 안 잡힌다.
2. `gh auth status`로 GitHub 로그인 확인 (진행 보드 권한이 없으면 `gh auth refresh -s project` 한 번), `git config user.email`이 GitHub 계정 이메일과 같은지 확인.
3. `.env.example`을 `.env`로 복사하고 각자 키를 넣는다 (`.env`는 git에 안 올라간다).
4. Docker Desktop을 켜고 `make up`으로 앱이 뜨는지 본다. 켜기·끄기·DB 다시 만들기는 [local-db.md](local-db.md).

## DB (로컬 Postgres)
Docker Desktop이 켜져 있어야 한다. docker 명령을 직접 칠 일은 없다. 자세한 표는 [local-db.md](local-db.md).
- 띄우기·스키마 맞추기: `make db` (Postgres + pgvector를 띄우고 `alembic upgrade head`까지). `git pull` 뒤에도 이것 한 줄. 서버도 켜질 때 upgrade 한다.
- 끄기: `make db-down` (데이터는 남는다). 처음부터 다시: `make db-reset` (데이터를 지운다).
- 검색 색인 받기: 팀 드라이브 색인 폴더에서 말뭉치마다 지금 색인 판(`<말뭉치>-idx-<색인 판>.dump`, 예 `law-idx-v1.dump`. 실험 설정의 `index_version`과 같은 것)을 받아 `data/index/`에 두고 `make index-load DUMP=data/index/<말뭉치>-idx-<색인 판>.dump`.
- 검색 색인 새로 만들어 나누기: 색인 스크립트 → `make index-dump` → 드라이브에 올리고 실험 설정 `index_version`을 바꾸는 PR (스크립트·덤프 규칙은 이슈 #65).
- 규칙: 스키마는 마이그레이션으로만, DB를 손으로 고치지 않는다. 자세한 건 [`src/patent_ai/db/CLAUDE.md`](../../src/patent_ai/db/CLAUDE.md).
- 막히면: `make db-reset` 뒤 `make index-load`. 그래도 안 되면 `docs/troubleshooting/`에 남긴다.

## 하루에 일하는 순서 (이슈 하나)
일감은 전부 GitHub 이슈로 있다 (M1·M2·M3 마일스톤, 저장소 Projects 탭의 진행 보드). 카드는 손으로 옮기지 않는다.
1. **고르기**: 보드에서 `Todo` 카드 중 지금 마일스톤 것, 본문 `먼저 끝나야 할 것`이 다 끝난 것을 고른다. 상대와 겹치지 않게 담당자를 자기로 넣는다.
2. **시작**: 저장소 폴더에서 `git switch main && git pull` → `claude` → `/start <이슈번호>`. 최신 main에서 `<type>/<번호>-<설명>` 브랜치가 `../wt/<번호>-<설명>`(저장소 폴더 옆)에 생기고 세션이 그리로 옮겨 가며, 카드가 `In Progress`로 간다. 원래 폴더는 main 그대로라 세션을 여러 개 열어 이슈를 동시에 해도 서로 안 건드린다. 처음 한 번 원래 폴더의 `.env`를 그 폴더로 복사하거나 링크한다. DB는 원래 폴더에서 띄운 것 하나를 같이 쓴다 (worktree에서 `make up` 하지 않는다). 지금 폴더에서 브랜치만 바꾸려면 `/start <이슈번호> --here`.
3. **일하기**: 구현 이슈는 `/implement <tasks.md> <m1-i3>` (구현 계획이 있어야 한다), tasks.md 없는 작은 이슈는 `/implement <이슈번호>` (이슈 본문 task 체크리스트와 확인 명령이 계획), 문서 이슈는 문서를 쓰고 `/doc-review <문서>`.
4. **올리기**: `/pr-draft` → 초안 보고 OK → Claude가 push·PR 생성 (`Closes #번호` 자동). 카드가 `In Review`로 간다.
5. **리뷰·머지**: 상대가 `/pr-review <PR번호>` → 승인되면 올린 사람이 머지(merge commit) → 이슈가 닫히고 카드가 `Done`. 브랜치는 머지 화면에서 지운다. 원래 폴더에서 `git worktree remove ../wt/<번호>-<설명>` → `git branch -d <브랜치>`.
6. 규칙·스킬(`.claude/`, `CLAUDE.md`)이 바뀐 PR이 머지되면 둘 다 `git pull` 하고 Claude Code를 새로 연다 (설정은 세션을 열 때 읽는다).
- 카드가 안 움직이면 Claude가 이유를 알려 준다. 대개 `gh auth refresh -s project`로 풀린다. 손으로 옮길 때는 `.claude/scripts/board-status.sh <이슈번호> "In Progress"`.

## 기능 하나를 만드는 순서 (자세한 표: [.claude/skills/README.md](../../.claude/skills/README.md))
1. **정하기**: `/interview <기능>` → requirements·design 쓰기 → `/doc-review <문서>` → 둘 다 승인
2. **계획**: 이터레이션 시작 때 `/plan-feature <기능> <m1-i3>` → tasks.md에 이슈 계획 → 승인 → "이슈 만들어" (이미 있는 이슈면 새로 만들지 않고 본문을 계획에 맞게 고친다)
3. **구현**: `/start <이슈번호>`로 브랜치를 만들고 `/implement <tasks.md> <m1-i3>` (task마다 테스트 먼저(실패는 로컬에서 확인) → 구현 → 통과하면 테스트와 함께 커밋 → 리뷰. 끝에 `/check`가 이어서 돈다)
4. **점수**: AI 동작을 바꿨으면 `/experiment <실험 이름>` (비용을 먼저 묻는다)
5. **PR**: `/pr-draft` → 초안 보고 OK → Claude가 push·PR 생성. push와 PR 생성은 매번 사람이 승인한다 (확인 창).
6. **리뷰**: 상대가 `/pr-review <번호>` → 판정 확인 뒤 "올려" → 승인되면 사람이 머지(merge commit)
- 머지·`main` push는 Claude가 하지 않는다.
