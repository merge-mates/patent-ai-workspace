# 팀원 시작 안내

## 처음 한 번 (클론한 날)
1. `git clone <레포 주소>` → `cd <폴더>` → `claude` 실행. "이 폴더를 신뢰" 질문에 허락한다 (그래야 팀 설정·스킬이 켜진다).
2. `gh auth status`로 GitHub 로그인 확인, `git config user.email`이 GitHub 계정 이메일과 같은지 확인.
3. `.env.example`을 `.env`로 복사하고 각자 키를 넣는다 (`.env`는 git에 안 올라간다).

## 기능 하나를 만드는 순서 (자세한 표: [.claude/skills/README.md](.claude/skills/README.md))
1. **정하기**: `/interview <기능>` → requirements·design 쓰기 → `/doc-review <문서>` → 둘 다 승인
2. **계획**: 이터레이션 시작 때 `/plan-feature <기능> <m1-i3>` → tasks.md에 이슈 계획 → 승인 → "이슈 만들어"
3. **구현**: 브랜치 만들고 `/implement <tasks.md> <m1-i3>` (task마다 테스트 먼저 → 구현 → 리뷰 → 커밋. 끝에 `/check`가 이어서 돈다)
4. **점수**: AI 동작을 바꿨으면 `/experiment <실험 이름>` (비용을 먼저 묻는다)
5. **PR**: `/pr-draft` → 초안 보고 OK → Claude가 push·PR 생성. push와 PR 생성은 매번 사람이 승인한다 (확인 창).
6. **리뷰**: 상대가 `/pr-review <번호>` → 판정 확인 뒤 "올려" → 승인되면 사람이 squash 머지
- 매일: `/daily` (데일리 스크럼 초안). 머지·`main` push는 Claude가 하지 않는다.
