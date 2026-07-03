"""FastAPI application factory and lifecycle orchestration."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.config import Settings
from app.dependencies import get_settings
from app.exceptions import AppError, app_error_handler, unhandled_exception_handler
from app.logging_config import configure_logging


class HealthResponse(BaseModel):
    """Liveness response payload."""

    status: Literal["ok"]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Own application startup and shutdown orchestration."""
    settings = get_settings()
    configure_logging(settings)
    register_lifecycle_hooks(app, settings)
    app.state.settings = settings
    try:
        yield
    finally:
        pass


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    app = FastAPI(title="AI Sales Engineer API", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.site.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["POST", "GET", "OPTIONS"],
        allow_headers=["Content-Type", "X-Site-Api-Key"],
    )

    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        """Return process liveness without dependency checks."""
        return HealthResponse(status="ok")

    return app


def register_lifecycle_hooks(app: FastAPI, settings: Settings) -> None:
    """Register future module lifecycle hooks without initializing integrations."""
    app.state.lifecycle_hooks_registered = True
    app.state.lifecycle_settings = settings

