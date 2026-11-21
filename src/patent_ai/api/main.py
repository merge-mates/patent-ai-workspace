"""FastAPI 앱. api/는 라우터만 두고 로직은 core/에 둔다 (ADR 0003 폴더)."""

from fastapi import FastAPI

from patent_ai.api import cases, documents, health, oas
from patent_ai.api.errors import add_error_handlers


def create_app() -> FastAPI:
    app = FastAPI(title="Patent AI Workspace API", version="0.1.0")
    add_error_handlers(app)
    app.include_router(health.router)
    app.include_router(cases.router)
    app.include_router(oas.router)
    app.include_router(documents.router)
    return app


app = create_app()
