"""FastAPI application factory and lifecycle orchestration."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_client import get_redis
from app.config import Settings
from app.db.engine import get_db_session
from app.dependencies import get_settings
from app.exceptions import AppError, app_error_handler, unhandled_exception_handler
from app.logging_config import configure_logging


class HealthResponse(BaseModel):
    """Liveness response payload."""

    status: Literal["ok"]


class DbHealthResponse(BaseModel):
    """Database readiness response payload."""

    status: Literal["ok", "error"]
    detail: str | None = None


class RedisHealthResponse(BaseModel):
    """Redis readiness response payload."""

    status: Literal["ok", "error"]
    detail: str | None = None


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
        for shutdown_hook in reversed(getattr(app.state, "shutdown_hooks", [])):
            await shutdown_hook()


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

    @app.get("/health/db", response_model=DbHealthResponse, response_model_exclude_none=True)
    async def health_db(session: AsyncSession = Depends(get_db_session)) -> DbHealthResponse:
        """Return database readiness by executing SELECT 1."""
        try:
            await session.execute(text("SELECT 1"))
        except Exception as exc:
            await session.rollback()
            logging.getLogger(__name__).error("Database health check failed: %s", exc)
            return DbHealthResponse(status="error", detail=str(exc))
        return DbHealthResponse(status="ok")

    @app.get("/health/redis", response_model=RedisHealthResponse, response_model_exclude_none=True)
    async def health_redis(redis: Redis = Depends(get_redis)) -> RedisHealthResponse:
        """Return Redis readiness by issuing PING."""
        try:
            await redis.ping()
        except Exception as exc:
            logging.getLogger(__name__).error("Redis health check failed: %s", exc)
            return RedisHealthResponse(status="error", detail=str(exc))
        return RedisHealthResponse(status="ok")

    return app


def register_lifecycle_hooks(app: FastAPI, settings: Settings) -> None:
    """Register module lifecycle hooks in startup order."""
    app.state.shutdown_hooks = []

    from app.cache.redis_client import register_hooks as register_redis_hooks
    from app.db.engine import register_hooks as register_db_hooks

    register_db_hooks(app, settings)
    register_redis_hooks(app, settings)
    app.state.lifecycle_hooks_registered = True
    app.state.lifecycle_settings = settings
