# 서버 라우터 (`src/patent_ai/api/`)
앱 폴더라 규칙이 가볍다: 테스트 먼저 대신 엔드포인트마다 API 테스트 몇 개(`tests/`, FastAPI `TestClient`). requirements·design·tasks와 tasks.md 진행 칸은 그대로 쓴다.
- 라우터만 둔다. 판단·계산 로직은 `core/`에 두고 부르기만 한다.
- 엔드포인트·상태 값·오류 규칙은 [docs/api/README.md](../../../docs/api/README.md)를 따른다.
- 오류는 `errors.AppError(status, code, message)`로 던진다. 본문은 `{code, message}` 한 형식 (FastAPI 기본 `{"detail"}` 아님).
- 요청·응답 스키마는 `response_model`로 건다. 결과 응답 스키마는 결과 스키마를 `result`에 담고 필드를 베껴 쓰지 않는다.
- 스키마가 바뀌면 docs/api/README.md 4절(breaking change 규칙)대로 한다.
