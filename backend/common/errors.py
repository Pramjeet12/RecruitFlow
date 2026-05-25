"""Standardized error handling — AppError hierarchy + FastAPI exception handlers."""
from enum import Enum
from typing import Any, Dict, Optional

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from common.logger import get_correlation_id, get_logger

logger = get_logger(__name__)


class ErrorCode(str, Enum):
    NOT_FOUND = "NOT_FOUND"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    INVALID_REQUEST = "INVALID_REQUEST"
    CONFLICT = "CONFLICT"
    INVALID_STATE = "INVALID_STATE"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    DUPLICATE_RESOURCE = "DUPLICATE_RESOURCE"
    FOREIGN_KEY_VIOLATION = "FOREIGN_KEY_VIOLATION"
    DB_INTEGRITY_ERROR = "DB_INTEGRITY_ERROR"
    OPTIMISTIC_LOCK_FAILED = "OPTIMISTIC_LOCK_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    DATABASE_ERROR = "DATABASE_ERROR"
    DB_CONNECTION_ERROR = "DB_CONNECTION_ERROR"
    DB_TIMEOUT = "DB_TIMEOUT"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    DRIVE_ACCESS_ERROR = "DRIVE_ACCESS_ERROR"
    CV_PROCESSING_ERROR = "CV_PROCESSING_ERROR"


class ErrorResponse(BaseModel):
    error: str
    message: str
    details: Optional[Dict[str, Any]] = None
    correlation_id: Optional[str] = None


class AppError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        status_code: int = 400,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)

    def to_response(self, correlation_id: Optional[str] = None) -> ErrorResponse:
        return ErrorResponse(
            error=self.code.value,
            message=self.message,
            details=self.details,
            correlation_id=correlation_id,
        )


class NotFoundError(AppError):
    def __init__(self, resource: str, identifier: Any) -> None:
        super().__init__(
            ErrorCode.NOT_FOUND,
            f"{resource} not found",
            404,
            {"resource": resource, "identifier": str(identifier)},
        )


class ValidationError(AppError):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(ErrorCode.VALIDATION_ERROR, message, 400, details)


class ConflictError(AppError):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(ErrorCode.CONFLICT, message, 409, details)


class UnauthorizedError(AppError):
    def __init__(self, message: str = "Unauthorized") -> None:
        super().__init__(ErrorCode.UNAUTHORIZED, message, 401)


class ForbiddenError(AppError):
    def __init__(self, message: str = "Forbidden") -> None:
        super().__init__(ErrorCode.FORBIDDEN, message, 403)


class InternalError(AppError):
    def __init__(self, message: str = "An internal error occurred") -> None:
        super().__init__(ErrorCode.INTERNAL_ERROR, message, 500)


class DriveAccessError(AppError):
    def __init__(self, message: str = "Could not access Google Drive folder") -> None:
        super().__init__(ErrorCode.DRIVE_ACCESS_ERROR, message, 502)


class CvProcessingError(AppError):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(ErrorCode.CV_PROCESSING_ERROR, message, 500, details)


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    correlation_id = get_correlation_id()
    if exc.status_code >= 500:
        logger.exception("AppError 5xx", extra={"code": exc.code.value, "path": request.url.path})
    else:
        logger.warning(
            "AppError",
            extra={"code": exc.code.value, "status": exc.status_code, "path": request.url.path},
        )
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_response(correlation_id).model_dump(exclude_none=True),
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    correlation_id = get_correlation_id()
    if isinstance(exc.detail, dict):
        details = exc.detail
        message = details.get("message") or "Request failed"
        error_code = details.get("error") or "ERROR"
    else:
        details = None
        message = str(exc.detail)
        error_code = _status_to_error_code(exc.status_code)
    response = ErrorResponse(
        error=error_code, message=message, details=details, correlation_id=correlation_id
    )
    return JSONResponse(status_code=exc.status_code, content=response.model_dump(exclude_none=True))


async def request_validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    correlation_id = get_correlation_id()
    response = ErrorResponse(
        error=ErrorCode.VALIDATION_ERROR.value,
        message="Request validation failed",
        details={"errors": exc.errors()},
        correlation_id=correlation_id,
    )
    return JSONResponse(status_code=422, content=response.model_dump(exclude_none=True))


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    correlation_id = get_correlation_id()
    logger.exception(
        "Unhandled exception",
        extra={"path": request.url.path, "method": request.method},
    )
    response = ErrorResponse(
        error=ErrorCode.INTERNAL_ERROR.value,
        message="An internal error occurred",
        correlation_id=correlation_id,
    )
    return JSONResponse(status_code=500, content=response.model_dump(exclude_none=True))


def _status_to_error_code(status_code: int) -> str:
    return {
        400: ErrorCode.INVALID_REQUEST.value,
        401: ErrorCode.UNAUTHORIZED.value,
        403: ErrorCode.FORBIDDEN.value,
        404: ErrorCode.NOT_FOUND.value,
        409: ErrorCode.CONFLICT.value,
        422: ErrorCode.VALIDATION_ERROR.value,
        500: ErrorCode.INTERNAL_ERROR.value,
        503: ErrorCode.SERVICE_UNAVAILABLE.value,
    }.get(status_code, ErrorCode.INTERNAL_ERROR.value)
