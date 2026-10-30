"""Small JSON logger without third-party logging dependencies."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from app.context import current_request_id, current_trace_id, current_user_id


_SENSITIVE_KEYS = ("api_key", "authorization", "token", "password", "secret", "cookie")


def _redact(value):
    if isinstance(value, dict):
        return {str(key): "[REDACTED]" if any(token in str(key).lower() for token in _SENSITIVE_KEYS) else _redact(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value[:100]]
    if isinstance(value, str):
        return value[:2000]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": _redact(record.getMessage()),
            "request_id": current_request_id(),
            "trace_id": current_trace_id(),
            "user_id": current_user_id(),
        }
        if record.exc_info:
            payload["exception"] = _redact(self.formatException(record.exc_info))
        for key in ("method", "path", "status_code", "duration_ms"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
