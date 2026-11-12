# Git 규칙 자세히
- 커밋 제목: `<type>(<영역>): <무엇을, 한국어 한 줄>` 50자 안팎, 마침표 없음.
  - type: `feat` 기능 / `fix` 버그 / `test` 테스트만 / `refactor` 동작 그대로 / `docs` 문서 / `chore` 설정·의존성. (Conventional Commits 흔한 목록. 따로 만든 type은 쓰지 않는다)
  - 영역: `backend` `frontend` `ai` `eval` `docs` `infra`
  - 예: `feat(backend): 목록 API에 날짜 필터 추가`, `feat(ai): <설정 값> 바꿔 비교 실험` (실험은 PR에 `실험` 라벨)
- 본문: "왜"가 제목만으로 안 보일 때만 2~4줄. 무엇을 했는지 나열하지 않는다 (diff에 있음).
- 꼬리: 이슈가 있으면 `Refs #12` (닫는 건 PR 본문의 `Closes #12`). Claude가 쓴 커밋은 `Co-Authored-By: Claude` 줄이 자동으로 붙는다. 지우지 않는다.
- 커밋 하나 = 테스트가 통과하는 한 단계. "WIP", "fix", "수정" 같은 제목 금지.
- 커밋 전에 `git diff --staged`를 보여 주고 키·비공개 파일·`data/`가 없는지 확인한다.
- 커밋은 Claude가 해도 된다. push·PR 생성은 사람이 PR 초안을 보고 OK한 뒤 Claude가 한다 (`/pr-draft`, push는 매번 확인 창). main에 직접 push하지 않는다. 머지는 사람이 한다 (settings.json deny).
