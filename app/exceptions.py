"""Application exception hierarchy and FastAPI exception handlers."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class AppError(Exception):
    """Base class for all application-level errors."""

    code: str = "app_error"
    message: str = "Application error"
    http_status: int = 500

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        http_status: int | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.http_status = http_status or self.http_status
        super().__init__(self.message)

    def to_response(self) -> dict[str, Any]:
        """Return the public JSON error payload."""
        return {"code": self.code, "message": self.message}


class NotFoundError(AppError):
    """Raised when a requested resource does not exist."""

    code = "not_found"
    message = "Resource not found"
    http_status = 404


class ValidationError(AppError):
    """Raised when application-level validation fails."""

    code = "validation_error"
    message = "Validation failed"
    http_status = 422


class ExternalServiceError(AppError):
    """Raised when an upstream service fails."""

    code = "external_service_error"
    message = "External service error"
    http_status = 502


class PolicyViolationError(AppError):
    """Raised when a security or execution policy is violated."""

    code = "policy_violation"
    message = "Policy violation"
    http_status = 403


class MissingConfigurationError(AppError):
    """Raised when required configuration keys are absent or empty."""

    code = "missing_configuration"
    http_status = 500

    def __init__(self, missing_keys: list[str]) -> None:
        self.missing_keys = sorted(missing_keys)
        keys = ", ".join(self.missing_keys)
        super().__init__(
            f"Missing required configuration values: {keys}",
            code=self.code,
            http_status=self.http_status,
        )

    def to_response(self) -> dict[str, Any]:
        """Return a public JSON payload listing all missing keys."""
        return {
            "code": self.code,
            "message": self.message,
            "missing_keys": self.missing_keys,
        }


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    """Map application errors to the common JSON error format."""
    return JSONResponse(status_code=exc.http_status, content=exc.to_response())


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a generic 500 response without leaking implementation details."""
    logger.exception("Unhandled exception while serving %s", request.url.path, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"code": "internal_error", "message": "Internal server error"},
    )
