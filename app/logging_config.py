"""Bootstrap logging configuration for Module 01."""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

from app.config import SENSITIVE_KEY_PARTS, Settings


class RedactingFilter(logging.Filter):
    """Redact secret-looking tokens from log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = _redact_text(str(record.msg))
        if record.args:
            record.args = tuple(_redact_text(str(arg)) for arg in record.args)
        return True


def configure_logging(settings: Settings) -> None:
    """Configure placeholder stdout logging for the application."""
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(settings.logging.log_level.upper())

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    handler.addFilter(RedactingFilter())
    root_logger.addHandler(handler)

    logging.getLogger(__name__).info(
        "Configuration loaded: %s; active feature flags: %s",
        settings.redacted_dict(),
        settings.flags.active_flags(),
    )


def _redact_text(value: Any) -> str:
    text = str(value)
    for marker in SENSITIVE_KEY_PARTS:
        text = re.sub(
            rf"({marker}['\"]?\s*[:=]\s*)['\"]?[^,'\"\s}}]+",
            rf"\1***REDACTED***",
            text,
            flags=re.IGNORECASE,
        )
    return text
