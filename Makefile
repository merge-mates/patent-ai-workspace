# 자주 쓰는 명령. docker 명령을 직접 칠 일이 없게 여기 모은다. 안내: docs/team/local-db.md
# 맥은 make가 기본으로 있다 (Xcode Command Line Tools).
.PHONY: help up down db db-down db-reset api test test-db lint index-load index-dump

COMPOSE := docker compose
DB_USER := $${POSTGRES_USER:-patent}
DB_NAME := $${POSTGRES_DB:-patent_ai}
# db 테스트 전용 DB. 개발 DB와 분리한다. 포트를 바꿨다면 make test-db TEST_DATABASE_URL=... 로 덮어쓴다
TEST_DB_NAME := patent_ai_test
TEST_DATABASE_URL ?= postgresql+psycopg://patent:patent@localhost:5432/$(TEST_DB_NAME)

help: ## 명령 목록
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-11s %s\n", $$1, $$2}'

up: ## DB·서버·화면을 다 띄운다 (서버가 켜질 때 마이그레이션 자동). 끝내려면 Ctrl+C 뒤 make down
	$(COMPOSE) up --build --renew-anon-volumes

down: ## 다 끈다 (DB 데이터는 남는다)
	$(COMPOSE) down

db: ## DB만 띄우고 마이그레이션을 끝까지 올린다
	$(COMPOSE) up -d --wait db
	uv run alembic upgrade head

db-down: ## DB만 끈다 (데이터는 남는다)
	$(COMPOSE) stop db

db-reset: ## DB를 지우고 처음부터 다시 만든다 (로컬 데이터가 전부 지워짐, 색인은 다시 불러와야 함)
	@read -p "로컬 DB 데이터를 전부 지웁니다. 계속할까요? [y/N] " ans && [ "$$ans" = "y" ]
	$(COMPOSE) down -v
	$(MAKE) db

api: ## 서버만 맥에서 바로 띄운다 (DB는 make db로 먼저). 화면 개발 서버는 web/에서 npm run dev
	uv run alembic upgrade head
	uv run uvicorn patent_ai.api.main:app --reload --reload-dir src

test: ## 파이썬 테스트 (DB·네트워크·API 키 없이)
	uv run pytest

test-db: ## 별도 테스트 DB(patent_ai_test)에서 @pytest.mark.db 테스트 (개발 DB는 안 건드림)
	$(COMPOSE) up -d --wait db
	@$(COMPOSE) exec -T db psql -U $(DB_USER) -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$(TEST_DB_NAME)'" | grep -q 1 \
	  || $(COMPOSE) exec -T db psql -U $(DB_USER) -d postgres -c "CREATE DATABASE $(TEST_DB_NAME)"
	DATABASE_URL="$(TEST_DATABASE_URL)" uv run alembic upgrade head
	DATABASE_URL="$(TEST_DATABASE_URL)" uv run pytest -m db

lint: ## 파이썬·화면 린트
	uv run ruff check
	uv run ruff format --check
	cd web && npm run lint

IDX := uv run python -m patent_ai.db.index_dump

index-load: ## 색인 덤프를 불러온다: make index-load DUMP=data/index/cite-idx-v1.dump (옆 .revision·.fingerprint.json이 없거나 다르면 멈춤)
	@test -n "$(DUMP)" || { echo "DUMP=<파일> 을 붙여 주세요. 예: make index-load DUMP=data/index/cite-idx-v1.dump"; exit 1; }
	@test -f "$(DUMP)" || { echo "파일이 없습니다: $(DUMP)"; exit 1; }
	$(COMPOSE) up -d --wait db
	$(IDX) check-before-load "$(DUMP)"
	$(COMPOSE) exec -T db sh -c 'pg_restore -U $(DB_USER) -d $(DB_NAME) --clean --if-exists --no-owner' < "$(DUMP)"
	$(IDX) check-after-load "$(DUMP)"

index-dump: ## 그 말뭉치 색인 표만 덤프로 뽑는다: make index-dump CORPUS=cite (data/index/<말뭉치>-idx-<판>.dump와 .revision·.fingerprint.json)
	@test -n "$(CORPUS)" || { echo "CORPUS=law 또는 CORPUS=cite 를 붙여 주세요"; exit 1; }
	$(COMPOSE) up -d --wait db
	@mkdir -p data/index
	@name=$$($(IDX) name "$(CORPUS)") || exit 1; \
	base="data/index/$${name%.dump}"; \
	cur=$$($(IDX) current-revision) || exit 1; \
	printf '%s\n' "$$cur" > "$$base.revision.tmp" \
	  && $(IDX) fingerprint "$(CORPUS)" > "$$base.fingerprint.json.tmp" \
	  && $(COMPOSE) exec -T db sh -c 'pg_dump -U $(DB_USER) -d $(DB_NAME) -Fc -t $(CORPUS)_chunks' > "data/index/$$name.tmp" \
	  && mv "data/index/$$name.tmp" "data/index/$$name" \
	  && mv "$$base.revision.tmp" "$$base.revision" \
	  && mv "$$base.fingerprint.json.tmp" "$$base.fingerprint.json" \
	  && echo "만듦: data/index/$$name, $$base.revision, $$base.fingerprint.json"
