"""FastAPI 앱. api/는 라우터만 두고 로직은 core/에 둔다 (ADR 0003 폴더)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from patent_ai.api import cases, deps, documents, health, oas, results, runs
from patent_ai.api.errors import add_error_handlers
from patent_ai.core.runs.recovery import fail_unfinished_runs
from patent_ai.core.runs.store import RunStatusStore


def create_app(startup_store: RunStatusStore | None = None) -> FastAPI:
    """startup_store: 켜질 때 끝나지 않은 실행을 정리할 저장소.

    lifespan에는 dependency_overrides가 안 먹어서 테스트는 이 인자로 메모리 저장소를 넘긴다.
    비우면 실제 Postgres 저장소를 켜질 때(lifespan 안에서) 만든다. TestClient를 `with` 없이
    쓰면 lifespan이 안 돌아 DB에 붙지 않는다.
    """

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # 서버가 꺼질 때 사라진 백그라운드 실행(queued·running)을 failed(server_restarted)로
        fail_unfinished_runs(startup_store or deps.get_run_status_store())
        yield

    app = FastAPI(title="Patent AI Workspace API", version="0.1.0", lifespan=lifespan)
    add_error_handlers(app)
    app.include_router(health.router)
    app.include_router(cases.router)
    app.include_router(oas.router)
    app.include_router(documents.router)
    app.include_router(runs.router)
    app.include_router(results.router)
    return app


app = create_app()
