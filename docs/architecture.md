---
상태: 초안
담당: 
---
# 전체 설계

## 1. 구성도
```
[브라우저] → [frontend] → [backend API] → [에이전트] → [모델 호출 모듈] → 모델 API
                                       └→ [수집 모듈(캐시·상한)] → KIPRIS Plus, 법령 API …
                                       └→ [그래프 검색 (인터페이스, config impl)]
                                       └→ [DB: Postgres — 사건 + pgvector + 그래프 노드·연결선 표]
```

## 2. 기술 선택
| 칸 | 고른 것 | 버린 것 | 이유 | 결정 문서 |
|---|---|---|---|---|
| 백엔드 | FastAPI, 패키지 uv | Spring | AI 코어와 같은 Python. Pydantic 스키마에서 OpenAPI 자동 | [ADR 0003](decisions/0003-tech-stack.md) |
| 프론트 | React + TypeScript (Vite) | Streamlit 등 Python 화면 | 화면 반응성, 사건·결과 다시 열기. TS 타입은 OpenAPI에서 | [ADR 0003](decisions/0003-tech-stack.md) |
| DB | Postgres 하나 (표 + jsonb + pgvector, 그래프 표) | 별도 벡터 DB, Neo4j | 자료를 한 곳에서, 판본 거르기와 벡터 검색을 한 쿼리로. 그래프는 인터페이스 뒤라 옮기기 쉬움 | [ADR 0003](decisions/0003-tech-stack.md) |
| 에이전트 | LangGraph, 실행 기록 Langfuse(compose 안) | SDK 도구 루프 직접, Claude Agent SDK, LangSmith | 지휘·서브·검증·사람 확인 전 멈춤을 상태 흐름으로. 기록이 밖으로 안 나감 | [ADR 0003](decisions/0003-tech-stack.md) |
| 모델 | 전부 Haiku 5.5 시작, 저지 OpenAI. 이름은 설정 파일 | Sonnet 기본 | 예산 안에서 많이 돌려 봄. 성능은 프롬프트·에이전트 설계로 | [ADR 0003](decisions/0003-tech-stack.md) |
| 배포 | 로컬 docker compose (Postgres·pgvector·Langfuse)로 시작. 발표용 웹 주소는 발표 형태 정할 때 | - (아직 비교 안 함) | 둘이 같은 개발 환경 | [ADR 0003](decisions/0003-tech-stack.md) |

## 3. 폴더
코드 폴더 모양은 프레임워크를 정할 때 같이 정한다.

## 4. 공통 규칙이 코드에서 어디에 있나
- 비용 기록: 
- 캐시: 
- 실험 설정(config): 

## 5. LLM·RAG·Agent·코드 역할 (후보)
| 역할 | 하는 일 | 하지 않을 일 |
|---|---|---|
| LLM | 청구항 요소 분석, 의미 비교, OA 요약, 보고서·의견서 초안 | 근거를 지어내기, 날짜·건수 계산 |
| RAG | 특허 원문·법령·심사기준에서 근거 검색 | 못 찾음을 부재로 확정 |
| 그래프 검색 | 1~2단계 관계로 후보를 넓히고 가져온 이유(경로)를 남김 | 경로 없이 "관련 있음"만 말하기 |
| Agent (사건 진행) | 사건 진행 전체: 무엇을 어떤 순서로, 다시 찾기, 보류, 사람에게 묻기. 코드·검색 도구를 부름 | 답이 정해진 일을 LLM에게 시키기 |
| 코드·도구 | 번호 정규화, 시점 필터, PDF 파싱, ID·JSON 검사 | 법률 판단 |
- 그래프 저장: 연결선은 (출발, 관계, 도착, 출처·판). 노드 ID는 고정한다 (출원번호, 문헌번호#문단).
- 구조: 지휘 에이전트 + 서브에이전트 (2026-11-16 팀 합의). 역할 후보: 자료 조사, 근거 검증, OA 분석, 초안 검토. 개수·세부는 ADR 0003.
- OA 대응 후보: 대비·분석과 근거 검토 역할 분리. 법률 조사 후보: 조사 진행·자료 조사·근거 검토 ([기획서 10절](product/service_plan_v3.1.md#10-ai-구성-원칙)). 패턴·개수는 기술 구조에서.

## 6. 열린 것
- 프레임워크·모델 선택 (DB는 2절)
- OA 당시 청구항 복원 방식 (이력 API vs 사용자 업로드). 3주는 사용자 업로드 ([product.md](product.md) 3.3절)

