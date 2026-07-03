"""Structured JSON logging configuration."""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone
from typing import Any

from app.config import SENSITIVE_KEY_PARTS, Settings

SECRET_KEY_PATTERN = re.compile(r"(KEY|SECRET|TOKEN|PASSWORD)", re.IGNORECASE)
STANDARD_LOG_RECORD_ATTRS = frozenset(logging.makeLogRecord({}).__dict__)


class JsonFormatter(logging.Formatter):
    """Render log records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in STANDARD_LOG_RECORD_ATTRS or key.startswith("_"):
                continue
            if key in {"user_message", "assistant_message", "prompt_text", "prompt"}:
                continue
            payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(_redact_value(payload), default=str, separators=(",", ":"))


class SecretRedactionFilter(logging.Filter):
    """Redact secret-looking tokens from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _redact_text(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = _redact_value(record.args)
            else:
                record.args = tuple(_redact_value(arg) for arg in record.args)
        for key, value in list(record.__dict__.items()):
            if key not in STANDARD_LOG_RECORD_ATTRS:
                setattr(record, key, _redact_value({key: value})[key])
        return True


RedactingFilter = SecretRedactionFilter


def configure_logging(settings: Settings) -> None:
    """Configure stdout JSON logging for the application."""
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(settings.logging.log_level.upper())

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(SecretRedactionFilter())
    root_logger.addHandler(handler)

    get_logger(__name__).info(
        "Configuration loaded: %s; active feature flags: %s",
        settings.redacted_dict(),
        settings.flags.active_flags(),
    )


def get_logger(name: str) -> logging.Logger:
    """Return a module logger for structured application logging."""
    return logging.getLogger(name)


def _redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "***REDACTED***" if SECRET_KEY_PATTERN.search(str(key)) else _redact_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item) for item in value)
    if isinstance(value, str):
        return _redact_text(value)
    return value


def _redact_text(value: Any) -> str:
    text = str(value)
    for marker in SENSITIVE_KEY_PARTS:
        text = re.sub(
            rf"({marker}['\"]?\s*[:=]\s*)['\"]?[^,'\"\s}}]+",
            r"\1***REDACTED***",
            text,
            flags=re.IGNORECASE,
        )
    return text
