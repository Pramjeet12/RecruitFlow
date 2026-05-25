"""SQLAlchemy exception translation."""
import asyncio
import functools
import re
from typing import Any, Callable, Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import (
    DataError,
    IntegrityError,
    NoResultFound,
    OperationalError,
    SQLAlchemyError,
    TimeoutError as SATimeoutError,
)

from common.errors import (
    AppError,
    ErrorCode,
    InternalError,
    ValidationError,
)
from common.logger import get_correlation_id, get_logger

logger = get_logger(__name__)


class DuplicateResourceError(AppError):
    def __init__(self, message: str, details: Optional[dict] = None) -> None:
        super().__init__(ErrorCode.DUPLICATE_RESOURCE, message, 409, details)


class ForeignKeyViolationError(AppError):
    def __init__(self, message: str, details: Optional[dict] = None) -> None:
        super().__init__(ErrorCode.FOREIGN_KEY_VIOLATION, message, 409, details)


class DBIntegrityError(AppError):
    def __init__(self, message: str, details: Optional[dict] = None) -> None:
        super().__init__(ErrorCode.DB_INTEGRITY_ERROR, message, 409, details)


class DBConnectionError(AppError):
    def __init__(self, message: str = "Database unavailable") -> None:
        super().__init__(ErrorCode.DB_CONNECTION_ERROR, message, 503)


class DBTimeoutError(AppError):
    def __init__(self, message: str = "Database timeout") -> None:
        super().__init__(ErrorCode.DB_TIMEOUT, message, 504)


class RecordNotFoundException(Exception):
    pass


_PG_UNIQUE = "23505"
_PG_FK = "23503"
_PG_NOT_NULL = "23502"
_PG_CHECK = "23514"


def _pgcode(exc: Exception) -> Optional[str]:
    orig = getattr(exc, "orig", None)
    return getattr(orig, "pgcode", None) if orig else None


def _parse_constraint(msg: str) -> Optional[str]:
    m = re.search(r'constraint "([^"]+)"', msg)
    return m.group(1) if m else None


def translate_sqlalchemy_error(exc: SQLAlchemyError) -> AppError:
    if isinstance(exc, IntegrityError):
        code = _pgcode(exc)
        constraint = _parse_constraint(str(exc.orig) if exc.orig else "")
        details = {"constraint": constraint} if constraint else None
        if code == _PG_UNIQUE:
            return DuplicateResourceError("Resource already exists", details)
        if code == _PG_FK:
            return ForeignKeyViolationError("Referenced resource does not exist", details)
        if code in (_PG_NOT_NULL, _PG_CHECK):
            return ValidationError("Constraint validation failed", details)
        return DBIntegrityError("Database integrity error", details)
    if isinstance(exc, DataError):
        return ValidationError("Invalid data for database column")
    if isinstance(exc, SATimeoutError):
        return DBTimeoutError()
    if isinstance(exc, OperationalError):
        msg = str(exc.orig) if exc.orig else str(exc)
        if any(tok in msg.lower() for tok in ("connection", "could not connect", "server closed")):
            return DBConnectionError()
        return InternalError("Database operational error")
    if isinstance(exc, NoResultFound):
        return InternalError("Expected single result, found none")
    return InternalError("Unhandled database error")


def handle_db_errors(func: Callable) -> Callable:
    if asyncio.iscoroutinefunction(func):
        @functools.wraps(func)
        async def awrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await func(*args, **kwargs)
            except AppError:
                raise
            except SQLAlchemyError as exc:
                logger.exception("DB error in %s", func.__qualname__)
                raise translate_sqlalchemy_error(exc) from exc
        return awrapper

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except AppError:
            raise
        except SQLAlchemyError as exc:
            logger.exception("DB error in %s", func.__qualname__)
            raise translate_sqlalchemy_error(exc) from exc
    return wrapper


async def sqlalchemy_exception_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    correlation_id = get_correlation_id()
    logger.exception("Untranslated SQLAlchemyError", extra={"path": request.url.path})
    app_err = translate_sqlalchemy_error(exc)
    return JSONResponse(
        status_code=app_err.status_code,
        content=app_err.to_response(correlation_id).model_dump(exclude_none=True),
    )
