# Patent Professional AI Workspace

국내 변리사·특허 실무자가 특허·논문·법률 자료를 조사하고 국내 의견제출통지서(OA)에 대응할 때, 출처와 근거가 연결된 조사 결과·문서 초안을 만들고 검증하게 돕는 AI 업무 공간.

> 상태: 기획 구체화 중 (2026-11). 아래 칸은 정해지는 대로 채운다.

## 주요 기능 (계획)
3주 범위: 국내 의견제출통지서(OA) 한 건을 올리면
1. 거절이유별로 정리한다.
2. 지적마다 법령·심사기준·판례 근거를 조사한다.
3. 청구항과 인용문헌을 대비한다.
4. 대응 방향 후보와 의견서·검토용 보정 청구항 초안을 만든다.

모든 결과에 원문 위치·판본·확인 상태를 붙인다. 자세한 건 [docs/product.md](docs/product.md).

- AI는 찾기·구조화·초안·검증을 돕고, 법률 판단과 최종 결정은 사람이 한다.
- 기술·경쟁사 조사, 선행기술 조사는 기획서에만 있다 (3주 밖).

## 데모
(시연 화면·영상, 11/27 시연 뒤)

## 기술 스택
FastAPI(uv, Python 3.14) · React+TypeScript(Vite, Node 26) · Postgres+pgvector · LangGraph. 이유는 [ADR 0003](docs/decisions/0003-tech-stack.md).

## 실행 방법
Docker(Desktop·OrbStack·colima 중 하나), uv, Node 26이 있으면 된다.
```
cp .env.example .env   # 키는 각자 채움 (없어도 뜬다)
make up                # DB·서버·화면, 서버가 켜질 때 마이그레이션 자동
```
화면 http://localhost:5173, 서버 http://localhost:8000/health. 테스트 `make test`, 린트 `make lint`, 명령 목록 `make help`. DB 켜기·끄기·다시 만들기·덤프 불러오기는 [docs/team/local-db.md](docs/team/local-db.md).

## 팀
2인 팀 프로젝트. 일하는 방식은 [docs/team/getting-started.md](docs/team/getting-started.md), 문서 지도는 [docs/README.md](docs/README.md).
