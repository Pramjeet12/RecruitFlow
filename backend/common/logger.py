"""Production logging: JSON formatter, correlation IDs, access log middleware."""
from __future__ import annotations

import json
import logging
import logging.handlers
import sys
import time
import uuid
from contextvars import ContextVar
from typing import Any, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from opentelemetry import trace

tracer = trace.get_tracer(__name__)

_correlation_id: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)


def get_correlation_id() -> Optional[str]:
    return _correlation_id.get()


def set_correlation_id(value: Optional[str]) -> None:
    _correlation_id.set(value)


class CorrelationIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id()
        return True


_RESERVED = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "asctime", "taskName", "correlation_id",
}


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S.%fZ"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self.service,
            "correlation_id": getattr(record, "correlation_id", None),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        return json.dumps(payload, default=str)


class PrettyFormatter(logging.Formatter):
    COLORS = {
        "DEBUG": "\033[36m", "INFO": "\033[32m", "WARNING": "\033[33m",
        "ERROR": "\033[31m", "CRITICAL": "\033[35m",
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        cid = getattr(record, "correlation_id", None) or "-"
        base = (
            f"{color}{record.levelname:<8}{self.RESET} "
            f"[{self.formatTime(record, '%H:%M:%S')}] "
            f"[{cid[:8]}] {record.name}: {record.getMessage()}"
        )
        extras = {
            k: v for k, v in record.__dict__.items()
            if k not in _RESERVED and not k.startswith("_")
        }
        if extras:
            base += f" | {extras}"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


_configured = False


def configure_logging(
    service: str,
    level: str = "INFO",
    env: str = "dev",
    log_file: Optional[str] = None,
    file_max_bytes: int = 10 * 1024 * 1024,
    file_backup_count: int = 5,
) -> None:
    global _configured
    if _configured:
        return

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level.upper())

    formatter: logging.Formatter = (
        JsonFormatter(service) if env.lower() == "prod" else PrettyFormatter()
    )
    cid_filter = CorrelationIdFilter()

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    stdout_handler.addFilter(cid_filter)
    root.addHandler(stdout_handler)

    if log_file:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=file_max_bytes, backupCount=file_backup_count, encoding="utf-8"
        )
        file_handler.setFormatter(JsonFormatter(service))
        file_handler.addFilter(cid_filter)
        root.addHandler(file_handler)

    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


logger = get_logger("recruitflow")


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    HEADER = "X-Request-ID"

    def __init__(self, app: ASGIApp, header: Optional[str] = None) -> None:
        super().__init__(app)
        self.header = header or self.HEADER

    async def dispatch(self, request: Request, call_next) -> Response:
        cid = request.headers.get(self.header) or str(uuid.uuid4())
        token = _correlation_id.set(cid)
        try:
            response = await call_next(request)
        finally:
            _correlation_id.reset(token)
        response.headers[self.header] = cid
        return response


class AccessLogMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, logger_name: str = "access") -> None:
        super().__init__(app)
        self._logger = get_logger(logger_name)

    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            self._logger.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": status_code,
                    "duration_ms": duration_ms,
                    "client": request.client.host if request.client else None,
                },
            )
