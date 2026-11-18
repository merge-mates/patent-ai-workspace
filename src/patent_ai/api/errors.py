"""오류 본문을 {code, message} 한 형식으로 맞춘다 (docs/api/README.md 2절)."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

_HTTP_CODES = {
    400: "bad_request",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
}


class AppError(Exception):
    """엔드포인트가 던지는 오류. code는 화면이 분기에 쓰는 고정 문자열이다."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _body(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"code": code, "message": message})


async def _app_error(_: Request, exc: AppError) -> JSONResponse:
    return _body(exc.status_code, exc.code, exc.message)


async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = _HTTP_CODES.get(exc.status_code, "http_error")
    return _body(exc.status_code, code, str(exc.detail))


async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    where = ".".join(str(p) for p in first.get("loc", ()))
    message = f"{where}: {first.get('msg', '요청 형식이 맞지 않습니다')}".strip(": ")
    return _body(422, "validation_error", message)


async def _unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    # 예상 못 한 예외: 내용은 로그에만 남기고, 응답 본문에는 내부 정보를 넣지 않는다
    logger.exception("처리하지 못한 예외: %s %s", request.method, request.url.path, exc_info=exc)
    return _body(500, "internal_error", "서버 오류가 났습니다")


def add_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unhandled_error)
