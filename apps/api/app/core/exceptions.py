"""Application error hierarchy and FastAPI exception handlers."""

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# Starlette renamed this constant; tolerate both.
HTTP_422 = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)

# Stable external error codes (SCREAMING_SNAKE).
VALIDATION_ERROR = "VALIDATION_ERROR"
ARTIFACT_MISSING = "ARTIFACT_MISSING"
ARTIFACT_TOO_LARGE = "ARTIFACT_TOO_LARGE"
ARTIFACT_INVALID_TYPE = "ARTIFACT_INVALID_TYPE"
BUILD_FAILED = "BUILD_FAILED"
SCAN_FAILED = "SCAN_FAILED"
TIMEOUT = "TIMEOUT"
DEPENDENCY_ERROR = "DEPENDENCY_ERROR"
INVALID_TRANSITION = "INVALID_TRANSITION"
NOT_FOUND = "NOT_FOUND"
UNAUTHORIZED = "UNAUTHORIZED"
FORBIDDEN = "FORBIDDEN"
CONFLICT = "CONFLICT"
INTERNAL_ERROR = "INTERNAL_ERROR"


class AppError(Exception):
    """Controlled application error with a stable error code and HTTP status."""

    def __init__(
        self,
        error_code: str,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.status_code = status_code
        self.context = context or {}


class NotFoundError(AppError):
    def __init__(self, message: str = "Resource not found", **context: Any) -> None:
        super().__init__(NOT_FOUND, message, status.HTTP_404_NOT_FOUND, context)


class ConflictError(AppError):
    def __init__(self, message: str = "Conflict", **context: Any) -> None:
        super().__init__(CONFLICT, message, status.HTTP_409_CONFLICT, context)


class InvalidTransitionError(AppError):
    def __init__(self, message: str, **context: Any) -> None:
        super().__init__(INVALID_TRANSITION, message, status.HTTP_409_CONFLICT, context)


def _error_body(error_code: str, message: str) -> dict[str, dict[str, str]]:
    return {"error": {"code": error_code, "message": message}}


def register_exception_handlers(app: FastAPI) -> None:
    """Attach safe, uniform error handling to the application."""

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        logger.info(
            "controlled error: %s",
            exc.message,
            extra={"error_code": exc.error_code, "path": request.url.path},
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(exc.error_code, exc.message),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        logger.debug(
            "validation error",
            extra={
                "error_code": VALIDATION_ERROR,
                "path": request.url.path,
                "errors": exc.errors(),
            },
        )
        return JSONResponse(
            status_code=HTTP_422,
            content=_error_body(VALIDATION_ERROR, "Request validation failed"),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "unhandled exception",
            extra={"error_code": INTERNAL_ERROR, "path": request.url.path},
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_body(INTERNAL_ERROR, "An internal error occurred"),
        )
