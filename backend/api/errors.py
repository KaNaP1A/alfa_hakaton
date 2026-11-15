import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException

from domain.errors import AppError
from domain.types import JsonValue

logger = logging.getLogger("uvicorn.error")


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: JsonValue = None


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


def error_response(
    status: int,
    code: str,
    message: str,
    details: JsonValue = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message, "details": details}},
        status_code=status,
        headers=headers,
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def application_error(request: Request, error: AppError) -> JSONResponse:
        return error_response(
            error.status,
            error.code,
            error.message,
            headers=dict(error.headers) if error.headers else None,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        details: JsonValue = [
            {"loc": list(item["loc"]), "msg": item["msg"], "type": item["type"]}
            for item in error.errors()
        ]
        return error_response(422, "validation_error", "Invalid request", details)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        return error_response(
            error.status_code,
            "http_error",
            str(error.detail),
            headers=dict(error.headers) if error.headers else None,
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, error: Exception) -> JSONResponse:
        logger.error("Unexpected failure: %s", type(error).__name__)
        return error_response(500, "internal_error", "Internal server error")
