"""오류 본문은 한 형식 {code, message} (docs/api/README.md 2절, FastAPI 기본 {"detail"} 대신)."""

from fastapi import APIRouter
from fastapi.testclient import TestClient

from patent_ai.api.errors import AppError
from patent_ai.api.main import create_app


def _client_with_test_routes() -> TestClient:
    app = create_app()
    router = APIRouter()

    @router.get("/_test/app-error")
    def raise_app_error():
        raise AppError(404, "oa_not_found", "OA를 찾을 수 없습니다")

    @router.get("/_test/needs-int/{n}")
    def needs_int(n: int):
        return {"n": n}

    app.include_router(router)
    return TestClient(app)


def test_app_error_uses_code_and_message():
    res = _client_with_test_routes().get("/_test/app-error")

    assert res.status_code == 404
    assert res.json() == {"code": "oa_not_found", "message": "OA를 찾을 수 없습니다"}


def test_unknown_path_uses_code_and_message():
    res = _client_with_test_routes().get("/no-such-path")

    assert res.status_code == 404
    body = res.json()
    assert set(body) == {"code", "message"}
    assert body["code"] == "not_found"


def test_validation_error_uses_code_and_message():
    res = _client_with_test_routes().get("/_test/needs-int/abc")

    assert res.status_code == 422
    body = res.json()
    assert set(body) == {"code", "message"}
    assert body["code"] == "validation_error"
