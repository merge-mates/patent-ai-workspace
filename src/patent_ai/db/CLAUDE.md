# DB 폴더 규칙 (`src/patent_ai/db/`)

이 폴더는 DB 모델(SQLAlchemy ORM, `base.py`의 `Base`를 상속)과 마이그레이션(Alembic, `migrations/`)을 둔다. 결정 배경: [ADR 0003](../../../docs/decisions/0003-tech-stack.md), [데이터 모델](../../../docs/data-model.md). 명령: [docs/team/local-db.md](../../../docs/team/local-db.md).

## 어디에 어떤 DB가 있나
- 두 사람 모두 각자 맥에서 docker compose로 같은 버전의 Postgres + pgvector를 띄운다 (`make db`). 공용 DB는 없다.
- 접속 주소는 `DATABASE_URL`(`src/patent_ai/settings.py`, 기본값은 로컬 compose DB). 코드에 주소를 쓰지 않는다.
- DB 내용은 세 종류다.

| 종류 | 예 | 둘이 같아야 하나 | 맞추는 법 |
|---|---|---|---|
| 스키마 | 테이블·컬럼·인덱스 | 예 | Alembic 마이그레이션 |
| 검색 색인 | 법령·심사기준 조각, 인용문헌 문단, 임베딩 | 예 (점수 비교 때문) | 색인 스크립트 + 색인 판 이름 + 덤프 공유 |
| 실행 결과 | 올린 사건, runs, agent_steps, 초안 | 아니오 | 각자. 공유할 점수는 `experiments/`의 `scores.json` |

## 스키마
- 스키마는 마이그레이션 파일로만 바꾼다. DB 모델을 고쳤으면 `uv run alembic revision --autogenerate -m "<무엇을>"`로 파일을 만들고, 생성된 파일을 읽어 고친 뒤 커밋한다 (autogenerate는 빠뜨리는 게 있다).
- 마이그레이션은 PR로만 들어간다. 상대 리뷰 필수.
- 둘이 동시에 마이그레이션을 만들어 head가 둘이 되면, 나중에 머지하는 쪽이 `down_revision`을 앞 것으로 바꿔 한 줄로 만든다. `alembic merge`는 쓰지 않는다.
- 이미 main에 들어간 마이그레이션 파일은 고치지 않는다. 바꿀 게 있으면 새 마이그레이션을 더한다.
- DB를 SQL로 손으로 고치지 않는다 (`psql`로 ALTER 등). 어긋나면 `make db-reset`으로 다시 만든다.
- 마이그레이션 적용은 `make db`·`make up`·`make api`가 자동으로 한다 (서버도 켜질 때 `alembic upgrade head`를 먼저 돈다).

## 검색 색인
- 색인은 색인 스크립트가 `data/raw/`와 색인 설정 파일(청킹 방식, 임베딩 모델)을 읽어 만든다. 만들 때 색인 판 이름(`index_version`, 예: `law-idx-v1`, `cite-idx-v1`)을 같이 저장한다. 말뭉치는 `law`(법령·심사기준·판례)와 `cite`(인용문헌)이고 말뭉치마다 표가 하나다. 계약은 [검색 계약 requirements](../../../docs/features/retrieval/requirements.md) (이슈 #65).
- 두 "판"을 섞지 않는다. **색인 판**(`index_version`, `idx-v1`·`idx-v2`)은 청킹·임베딩 설정을 바꾸면 올리는 것이고, 덤프 파일 이름의 판은 이것이다. **법령 판본**은 시행일별 법령·심사기준이고, 한 색인 판 안에 여러 판본이 같이 들어간다.
- 임베딩 비용이 두 번 들지 않게, 한 사람이 만들고 덤프로 나눈다.
  - 만든 사람: 자기 말뭉치 색인 테이블 하나만 `pg_dump -Fc`로 `<말뭉치>-idx-<색인 판>.dump`(예: `law-idx-v1.dump`, `cite-idx-v1.dump`)를 뽑아 팀 드라이브의 색인 폴더에 올린다. 파일 이름의 색인 판은 덤프에 든 가장 높은 색인 판이다 (`make index-dump`, 이슈 #65 구현에서 채움).
  - 받는 사람: 드라이브에서 받아 `data/index/`에 두고 `make index-load DUMP=data/index/<말뭉치>-idx-<색인 판>.dump`. 그 말뭉치 표만 바뀌고 다른 말뭉치 표는 그대로다.
  - 실행 결과 테이블은 덤프에 넣지 않는다. 덤프는 git에 넣지 않는다.
- 새 색인 판은 덮어쓰지 않는다. 설정을 바꾼 말뭉치만 `<말뭉치>-idx-v2`로 새로 만들고(다른 말뭉치는 v1 그대로), 실험 설정의 `index_version`을 바꾸는 PR로 알린다.
- 실험 설정에는 `index_version`을 적는다. 채점 스크립트는 DB의 색인 판이 설정과 다르면 멈춘다. 이 검사를 끄지 않는다.

## 테스트
- AI 코어·코드 도구 테스트는 DB 없이 돈다: DB 접근은 repository 인터페이스 뒤에 두고, 테스트는 메모리 fake를 쓴다.
- 실제 Postgres가 필요한 테스트(마이그레이션, pgvector 검색)는 `@pytest.mark.db`를 붙인다. 기본 `uv run pytest`에서는 빠지고, 로컬은 `make db`를 띄운 뒤 `make test-db`, CI는 GitHub Actions의 Postgres(pgvector) 서비스 컨테이너로 돈다.
- 테스트는 네트워크·API 키 없이 돈다 (임베딩은 녹화 응답).

## 나중에 바뀔 수 있는 것
- 한 사람이 Docker가 어려우면 클라우드 Postgres(Supabase)로 옮긴다. 같은 Postgres + pgvector라 덤프를 올리고 접속 문자열(`.env`의 `DATABASE_URL`)만 바꾼다. 공용 DB로 가면 "main에 머지된 마이그레이션만 CI가 공용 DB에 적용"으로 바꾼다.
- 지식 그래프를 넣게 되면 그래프 DB(Neo4j)는 Postgres에서 스크립트로 만드는 파생 저장소로 두고, 손으로 고치지 않는다.
