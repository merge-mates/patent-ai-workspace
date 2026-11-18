# 로컬 개발 환경과 DB

각자 맥에서 docker compose로 Postgres(+pgvector)를 띄운다. 공용 클라우드 DB는 없다 (발표용 웹 주소가 필요할 때 다시 본다). docker 명령은 직접 치지 않고 `make`로 한다. `make help`로 목록을 본다.

## 처음 한 번
1. Docker Desktop을 설치하고 켠다 (메뉴 막대에 고래 아이콘).
2. 저장소 폴더에서 `uv sync`, `cd web && npm ci` (Python·Node 패키지 설치).
3. `.env.example`을 `.env`로 복사한다. 키가 비어 있어도 앱은 뜬다.

## 켜기·끄기
| 하려는 것 | 명령 | 데이터 |
|---|---|---|
| 앱 전체(DB·서버·화면) 켜기 | `make up` | 화면 http://localhost:5173, 서버 http://localhost:8000/health |
| 앱 전체 끄기 | Ctrl+C 뒤 `make down` | 남는다 |
| DB만 켜고 마이그레이션 올리기 | `make db` | 남는다 |
| 서버만 맥에서 바로 띄우기 (디버거 붙일 때) | `make db` 뒤 `make api` | 남는다 |
| DB만 끄기 | `make db-down` | 남는다 |
| 실제 DB가 필요한 테스트 (`@pytest.mark.db`) | `make db` 뒤 `make test-db` | 남는다 |
| 처음부터 다시 | `make db-reset` (확인을 묻는다) | **전부 지워진다.** 색인은 다시 불러온다 |

- 마이그레이션(`alembic upgrade head`)은 `make up`·`make db`·`make api`가 자동으로 한다. 손으로 칠 일은 없다.
- 마이그레이션 파일 만드는 법과 규칙은 [`src/patent_ai/db/CLAUDE.md`](../../src/patent_ai/db/CLAUDE.md).
- 데이터는 docker 볼륨(`patent-ai_db-data`)에 남는다. 맥을 껐다 켜도 그대로다.

## 덤프 불러오기 (검색 색인)
색인은 한 사람이 만들어 `pg_dump -Fc` 파일로 드라이브에 올리고(`make index-dump CORPUS=cite`), 받는 쪽은 `data/index/`에 받아 불러온다. 덤프 파일 이름은 `<말뭉치>-idx-<색인 판>.dump`(예: `law-idx-v1.dump`, `cite-idx-v1.dump`)이고, 규칙은 [db/CLAUDE.md](../../src/patent_ai/db/CLAUDE.md) 검색 색인 절.
```
make index-load DUMP=data/index/law-idx-v1.dump
```
- 덤프 옆 `.revision`이 내 DB의 마이그레이션 revision과 다르면 멈춘다. `make db`로 맞춘 뒤 다시 한다. 옆 파일이 없으면 경고만 하고 넣는다.
- 손 확인(가짜 조각): `make db` 뒤 `uv run python -m patent_ai.db.index_dump load-fixture cite tests/fixtures/retrieval/chunks_cite.jsonl`, `make index-dump CORPUS=cite`로 `data/index/cite-idx-v1.dump`·`.revision`이 생기는지 본다.
- 덤프에 든 테이블만 지우고 다시 만든다 (`pg_restore --clean`). 다른 테이블은 그대로다.
- 덤프는 git에 올리지 않는다.

## 막힐 때
| 증상 | 할 것 |
|---|---|
| `Cannot connect to the Docker daemon` | Docker Desktop을 켠다 |
| `port is already allocated` (5432·8000·5173) | 맥에 이미 Postgres 등이 떠 있다. `.env`에 `DB_PORT=5433`처럼 다른 포트를 쓰고, `make api`·`make db`를 쓸 거면 `DATABASE_URL`도 같은 포트로 적는다 (`postgresql+psycopg://patent:patent@localhost:5433/patent_ai`) |
| 서버가 안 뜨고 `alembic` 오류 | 마이그레이션이 실패하면 서버도 안 뜬다. 오류를 보고, 로컬 데이터가 없어도 되면 `make db-reset` |
