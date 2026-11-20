# 스킬 목록

스킬 = 부를 때만 읽히는 절차서 (어떻게). 에이전트(`.claude/agents/*.md`) = 스킬이 일을 맡기는 하위 일꾼 (누가). `/이름 인자`로 부른다.
- 모든 스킬은 `/이름`으로 쳐도 되고, 말로 부탁해도 Claude가 설명을 보고 부른다 (`disable-model-invocation`을 쓰지 않음). 무거운 일의 멈춤은 스킬 안에 둔다: implement는 승인된 계획이 없으면 멈추고, pr-review는 사람이 "올려"라고 해야 제출하고, push·PR 생성은 매번 확인 창.
- **이어서 불리는 스킬**: check, pr-draft, experiment. 예: `/implement`가 끝나면 본문 지시대로 `/check 이슈` → `/pr-draft`를 Claude가 이어서 부른다. experiment는 돌리기 전에 비용을 말하고 사람에게 묻는다.
- 이어지는 순서는 각 SKILL.md 본문에 적는다. 따로 오케스트레이터 파일은 없다 (`/implement`가 그 역할).
- 용어: **이슈** = 사람이 진행을 보는 단위. tasks.md 이슈 계획(`## m1-i3`) 하나 이상. **계획** 하나 = 브랜치 하나 = PR 하나. **task** = 이슈 안의 atomic 단위 (혼자 끝나고 혼자 검증되는 가장 작은 단위, 반나절 안쪽, 확인 방법 명령 한 줄).

| 스킬 | 언제 | 부르는 에이전트 | 결과 |
|---|---|---|---|
| `/interview <기능>` | 기획안·requirements 쓰기 전, 모호할 때 | researcher (사실 찾기) | 질문 창(AskUserQuestion)으로 결정만 묻고, 문서 브랜치에 바로 씀 + 용어집, [가정], 열린 질문 |
| `/doc-review <문서>` | 문서를 "다 썼다" 하기 전 | critic | 판정 + 지적 + 체크리스트 표 |
| `/plan-feature <기능> <이터레이션>` | 이터레이션 시작 | plan-reviewer | tasks.md 이슈 계획 (task마다 확인 방법), (원하면) 이슈 |
| `/start <이슈번호> [--here]` | 이슈 하나 시작 (구현·문서 모두) | 없음 | 최신 main에서 `<type>/<번호>-<설명>` 브랜치를 `../wt/<이슈번호>-<짧은설명>` worktree로 (세션마다 폴더 따로. `--here`면 지금 폴더), 보드 카드 In Progress |
| `/implement <tasks.md> <이터레이션>` 또는 `/implement <이슈번호>` | 계획 하나 시작 (작은 이슈는 이슈 본문 체크리스트가 계획, 진행은 본문 체크박스) | task마다 implementer → code-reviewer → 고침 → 테스트 → 커밋 (겹치지 않는 task는 워크트리에서 동시에), 끝에 /check 이슈 | 코드 + 커밋 + PR 재료 |
| `/check <이슈\|기능> …` | PR 전(이슈), 기능 끝(기능) | verifier → code-reviewer | 증거 + 문서 대조 표 |
| `/experiment <실험>` | AI 점수 낼 때 (이슈 끝, 마일스톤 끝) | experiment-analyst | scores.json, card.md, index.md |
| `/pr-draft` | PR 열기 전 | 없음 | work/pr-draft.md, push·PR 생성은 매번 사람 승인 (확인 창) |
| `/pr-review <번호>` | 상대 PR 리뷰 | code-reviewer | 판정 제안 + 지적 목록 (사람 확인 뒤 제출) |

## 흐름 한 장
```
기획안 ─/interview─/doc-review→ docs/product.md (둘 다 승인)
  └ 기능마다 requirements ─/doc-review→ design ─/doc-review→ (승인)
  마일스톤(product.md 9절: M1 OA 정리, M2 근거와 대비, M3 대응 초안과 평가) 안에서
       └ 이터레이션(하루~이틀)마다 /plan-feature → tasks.md 이슈 계획 → PR 하나 (이슈 하나에 계획 여러 개 가능)
            └ /start 이슈번호 (../wt/ worktree) → /implement (task마다 구현·리뷰·고침·테스트·커밋, 겹치지 않는 task는 동시에) → /check 이슈
              → (AI 동작을 바꿨으면) /experiment, tune 세트
              → /pr-draft → (사람 OK, 매번 확인 창) Claude가 push·PR 생성 → 상대 /pr-review → (사람) 머지
       └ 기능이 끝나면 /check 기능
  마일스톤 끝: code-reviewer 마일스톤 모드 → 다음 마일스톤 이슈
                 └ AI면 /experiment, report 세트 → card.md
```

## 진행 보드 (저장소 Projects 탭)
칸 옮기기는 이렇게 된다. 가운데 두 칸은 스킬이 `.claude/scripts/board-status.sh`를 불러 옮긴다 (훅은 이슈 #83에서 뺐다: 명령 글자로 이슈를 짐작하다 엉뚱한 카드를 옮김).
| 언제 | 칸 | 누가 |
|---|---|---|
| 이슈를 만들면 | Todo | GitHub 보드 규칙 (열린 이슈 자동 추가) |
| `/start`로 브랜치를 만들면 (`git worktree add -b <type>/<번호>-…`, `--here`면 `git switch -c`) | In Progress | `/start` 6번 |
| `/pr-draft` 뒤 PR을 만들면 (`gh pr create`) | In Review | `/pr-draft` 6번 |
| 이슈의 마지막 PR이 머지되면 (본문 `Closes #N`. `Refs #N` PR은 카드를 옮기지 않는다) | Done | GitHub 보드 규칙 (이슈 닫힘) |

- 보드 번호, Status 필드·옵션 id는 어디에도 적지 않는다. `.claude/scripts/board-status.sh <이슈번호> "<칸>"`이 매번 gh로 찾는다. 스킬 없이 손으로 브랜치·PR을 만들었으면 이 스크립트로 옮긴다.
- 사람마다 한 번 `gh auth refresh -s project` (보드 권한). 없으면 스크립트가 이유를 알려 준다.
- 칸 이름(Todo / In Progress / In Review / Done)을 바꾸면 스킬의 칸 이름도 같이 바꾼다.

## 고치는 법
- 같은 지시를 **두 번** 손으로 하면 `docs/team/rules-candidates.md`에 올리고 스킬 후보로 본다. 한 번도 안 쓴 스킬은 마일스톤 회고에서 빼거나 고친다.
- 스킬을 고치면 PR. 고친 이유를 커밋 본문에 한 줄.
- SKILL.md는 500줄 아래 (공식 문서 권장). 긴 체크리스트는 `references/`로.
- 내장 스킬과 이름이 겹치지 않게 한다. 예: `verify`는 내장 이름이라 `check`로 쓴다 (프로젝트에 `verify`가 있으면 Claude가 매 커밋 전에 돌리라는 지시를 받는다, 공식 문서 Skills).
- 참고한 오픈소스 (아이디어만, 원문 복사 없음): oh-my-claudecode·gajae-code (MIT, Yeachan Heo)의 verify·deep-interview·critic·scientist·review, grill-with-docs (MIT, Matt Pocock).
