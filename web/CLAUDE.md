# 화면 (`web/`, React + TypeScript, Vite)
앱 폴더라 규칙이 가볍다: 테스트 먼저는 하지 않는다. requirements·design·tasks와 tasks.md 진행 칸은 그대로 쓴다.
- 명령(이 폴더 안에서): `npm run dev`, `npm run lint`(oxlint), `npm run build`(타입 검사 포함). 보통은 루트에서 `make up`.
- `npm run test` (runPoll.ts만 단위 테스트, 다른 화면 코드는 두지 않음). CI web job에서도 돈다
- 서버 API가 생기기 전에는 mock으로 본다: `VITE_API_MODE=mock npm run dev` (fixture를 돌려준다. `make up` 기본은 서버 모드라 서버가 없으면 오류가 보인다).
- Node 버전은 `.nvmrc`(26). 패키지를 더하면 `package-lock.json`도 같이 커밋한다.
- 서버는 `/api/*`로만 부른다. 개발 서버가 FastAPI로 넘긴다(`vite.config.ts` proxy). 서버 주소를 코드에 쓰지 않는다.
- 서버 응답 타입은 OpenAPI에서 뽑는다(도구는 화면 설계에서). 손으로 같은 타입을 다시 쓰지 않는다. 서버가 생기기 전에는 `tests/fixtures/` 가짜 결과 파일로 만든다.
- AI 결과와 사람이 고르거나 고친 것을 화면에서 구분해 보인다 (루트 CLAUDE.md 특허 도메인 규칙).
