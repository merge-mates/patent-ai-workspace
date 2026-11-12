# 스킬 목록

스킬 = 부를 때만 읽히는 절차서 (어떻게). 에이전트(`.claude/agents/*.md`) = 스킬이 일을 맡기는 하위 일꾼 (누가). `/이름 인자`로 부른다.
- **사람이 시작하는 스킬** (`disable-model-invocation: true`): interview, doc-review, plan-feature, implement, pr-review, daily. 말로는 안 불리고 `/이름`으로 직접 친다.
- **이어서 불리는 스킬** (자동 호출 허용): check, pr-draft, experiment. 예: `/implement`가 끝나면 본문 지시대로 `/check 이슈` → `/pr-draft`를 Claude가 이어서 부른다. experiment는 돌리기 전에 비용을 말하고 사람에게 묻는다.
- 이어지는 순서는 각 SKILL.md 본문에 적는다. 따로 오케스트레이터 파일은 없다 (`/implement`가 그 역할).
- 용어: **이슈** = tasks.md의 이슈 계획 하나(`## m1-i3`) = 브랜치 하나 = PR 하나. **task** = 이슈 안의 반나절 단계.

| 스킬 | 언제 | 부르는 에이전트 | 결과 |
|---|---|---|---|
| `/interview <기능>` | 기획안·requirements 쓰기 전, 모호할 때 | 없음 | 정한 것, [가정], 열린 질문 |
| `/doc-review <문서>` | 문서를 "다 썼다" 하기 전 | critic | 판정 + 지적 + 체크리스트 표 |
| `/plan-feature <기능> <이터레이션>` | 이터레이션 시작 | plan-reviewer | tasks.md 이슈 계획, (원하면) 이슈 |
| `/implement <tasks.md> <이터레이션>` | 이슈 하나 시작 | task마다 implementer → code-reviewer → 고침 → 테스트 → 커밋, 끝에 /check 이슈 | 코드 + 커밋 + PR 재료 |
| `/check <이슈\|기능> …` | PR 전(이슈), 기능 끝(기능) | verifier → code-reviewer | 증거 + 문서 대조 표 |
| `/experiment <실험>` | AI 점수 낼 때 (이슈 끝, 마일스톤 끝) | experiment-analyst | scores.json, card.md, index.md |
| `/pr-draft` | PR 열기 전 | 없음 | work/pr-draft.md, 사람 OK 뒤 push·PR |
| `/pr-review <번호>` | 상대 PR 리뷰 | code-reviewer | 판정 제안 + 지적 목록 (사람 확인 뒤 제출) |
| `/daily [change]` | 데일리 스크럼 전후 | 없음 | docs/team/daily 초안 (막힘·이유는 사람이) |

## 흐름 한 장
```
기획안 ─/interview─/doc-review→ docs/product.md (둘 다 승인)
  └ 기능마다 requirements ─/doc-review→ design ─/doc-review→ (승인)
  마일스톤(M1=MVP, M2 …) 안에서
       └ 이터레이션(하루~이틀)마다 /plan-feature → tasks.md 이슈 계획 → 이슈 하나
            └ /implement (task마다 구현·리뷰·고침·테스트·커밋) → /check 이슈
              → (AI 동작을 바꿨으면) /experiment, tune 세트
              → /pr-draft → (사람 OK) Claude가 push·PR → 상대 /pr-review → (사람) 머지
       └ 기능이 끝나면 /check 기능
  마일스톤 끝: code-reviewer 마일스톤 모드 → 다음 마일스톤 이슈
                 └ AI면 /experiment, report 세트 → card.md
  매일 /daily → 데일리 스크럼 (이터레이션이 바뀌는 날은 비교·머지·다음 계획)
```

## 고치는 법
- 같은 지시를 **두 번** 손으로 하면 `docs/team/rules-candidates.md`에 올리고 스킬 후보로 본다. 한 번도 안 쓴 스킬은 마일스톤 회고에서 빼거나 고친다.
- 스킬을 고치면 PR. 고친 이유를 커밋 본문에 한 줄.
- SKILL.md는 500줄 아래 (공식 문서 권장). 긴 체크리스트는 `references/`로.
- 내장 스킬과 이름이 겹치지 않게 한다. 예: `verify`는 내장 이름이라 `check`로 쓴다 (프로젝트에 `verify`가 있으면 Claude가 매 커밋 전에 돌리라는 지시를 받는다, 공식 문서 Skills).
- 참고한 오픈소스 (아이디어만, 원문 복사 없음): oh-my-claudecode·gajae-code (MIT, Yeachan Heo)의 verify·deep-interview·critic·scientist·review.
