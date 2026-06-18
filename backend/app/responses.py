from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


def new_trace_id() -> str:
    return uuid4().hex


def envelope(
    data: Any = None,
    *,
    code: int = 0,
    msg: str = "ok",
    trace_id: str | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "msg": msg,
        "data": data,
        "trace_id": trace_id or new_trace_id(),
    }


def ok(data: Any = None, *, msg: str = "ok") -> dict[str, Any]:
    return envelope(data, msg=msg)


@dataclass
class ApiError(Exception):
    code: int
    msg: str
    status_code: int = 400
    data: Any = None


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=envelope(exc.data, code=exc.code, msg=exc.msg),
    )


async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content=envelope(exc.errors(), code=40001, msg="invalid request"),
    )
