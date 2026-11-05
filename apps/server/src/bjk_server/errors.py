"""공통 오류 형식 (API 명세서 1-3). 모든 오류는 {code, message, detail}로 응답한다."""

from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ErrorCode(StrEnum):
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNAUTHORIZED = "UNAUTHORIZED"
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    INVALID_PIN = "INVALID_PIN"
    FORBIDDEN_ROLE = "FORBIDDEN_ROLE"
    SELF_APPROVAL_NOT_ALLOWED = "SELF_APPROVAL_NOT_ALLOWED"
    NOT_FOUND = "NOT_FOUND"
    EMAIL_TAKEN = "EMAIL_TAKEN"
    NAME_TAKEN = "NAME_TAKEN"
    ALREADY_CONFIRMED = "ALREADY_CONFIRMED"
    IDEMPOTENCY_CONFLICT = "IDEMPOTENCY_CONFLICT"
    REVIEW_ALREADY_DECIDED = "REVIEW_ALREADY_DECIDED"
    REVIEW_NOT_DECIDABLE = "REVIEW_NOT_DECIDABLE"
    SNAPSHOT_REFRESHED = "SNAPSHOT_REFRESHED"
    ORDER_STATE_CONFLICT = "ORDER_STATE_CONFLICT"
    PDF_NOT_READY = "PDF_NOT_READY"
    ENTRY_EXPIRED = "ENTRY_EXPIRED"
    INVITE_EXPIRED = "INVITE_EXPIRED"
    REASON_REQUIRED = "REASON_REQUIRED"
    PART_NOT_RESOLVED = "PART_NOT_RESOLVED"
    PIN_LOCKED = "PIN_LOCKED"
    RATE_LIMITED = "RATE_LIMITED"


STATUS: dict[ErrorCode, int] = {
    ErrorCode.VALIDATION_ERROR: 400,
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.INVALID_CREDENTIALS: 401,
    ErrorCode.INVALID_PIN: 401,
    ErrorCode.FORBIDDEN_ROLE: 403,
    ErrorCode.SELF_APPROVAL_NOT_ALLOWED: 403,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.EMAIL_TAKEN: 409,
    ErrorCode.NAME_TAKEN: 409,
    ErrorCode.ALREADY_CONFIRMED: 409,
    ErrorCode.IDEMPOTENCY_CONFLICT: 409,
    ErrorCode.REVIEW_ALREADY_DECIDED: 409,
    ErrorCode.REVIEW_NOT_DECIDABLE: 409,
    ErrorCode.SNAPSHOT_REFRESHED: 409,
    ErrorCode.ORDER_STATE_CONFLICT: 409,
    ErrorCode.PDF_NOT_READY: 409,
    ErrorCode.ENTRY_EXPIRED: 410,
    ErrorCode.INVITE_EXPIRED: 410,
    ErrorCode.REASON_REQUIRED: 422,
    ErrorCode.PART_NOT_RESOLVED: 422,
    ErrorCode.PIN_LOCKED: 423,
    ErrorCode.RATE_LIMITED: 429,
}


class ApiError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        detail: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}
        self.headers = headers

    @property
    def status_code(self) -> int:
        return STATUS[self.code]


def error_body(code: ErrorCode, message: str, detail: dict[str, Any] | None = None) -> dict:
    return {"code": code.value, "message": message, "detail": detail or {}}


async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        error_body(exc.code, exc.message, exc.detail), exc.status_code, headers=exc.headers
    )


async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
    body = error_body(
        ErrorCode.VALIDATION_ERROR, "입력 형식이 올바르지 않습니다.", {"errors": errors}
    )
    return JSONResponse(body, 400)


async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    # 라우팅 단계의 404·405 등도 같은 형식으로 돌려준다.
    if exc.status_code == 404:
        body = error_body(ErrorCode.NOT_FOUND, "리소스를 찾을 수 없습니다.")
    else:
        body = {"code": f"HTTP_{exc.status_code}", "message": str(exc.detail), "detail": {}}
    return JSONResponse(body, exc.status_code, headers=getattr(exc, "headers", None))


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
