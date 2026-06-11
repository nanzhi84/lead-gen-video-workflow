from __future__ import annotations

import json
import logging
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from typing import Any

from packages.core.observability.telemetry import REQUIRED_LOG_FIELDS


_LOG_CONTEXT: ContextVar[dict[str, Any]] = ContextVar("cutagent_log_context", default={})
_RESERVED_LOG_RECORD_KEYS = set(logging.makeLogRecord({}).__dict__)


def bind_observability_context(**values: Any) -> Token:
    context = {**_LOG_CONTEXT.get()}
    for key, value in values.items():
        if key in REQUIRED_LOG_FIELDS:
            context[key] = value
    return _LOG_CONTEXT.set(context)


def reset_observability_context(token: Token) -> None:
    _LOG_CONTEXT.reset(token)


def clear_observability_context() -> None:
    _LOG_CONTEXT.set({})


def observability_context() -> dict[str, Any]:
    return {field: _LOG_CONTEXT.get().get(field) for field in REQUIRED_LOG_FIELDS}


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        context = observability_context()
        for field in REQUIRED_LOG_FIELDS:
            payload[field] = getattr(record, field, context.get(field))

        for key, value in record.__dict__.items():
            if key in _RESERVED_LOG_RECORD_KEYS or key in payload:
                continue
            payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonLogFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
