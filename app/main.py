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
    """Own application startup and shutdown orchestration with strict safety bounds."""
    import asyncio

    settings = get_settings()
    configure_logging(settings)

    from app.cache.redis_client import close_redis, initialize_redis
    from app.db.engine import dispose_database, initialize_database, get_sessionmaker

    logger = logging.getLogger(__name__)

    try:
        # Initialize Redis client (no network I/O)
        initialize_redis(settings)
        # Initialize Database Engine (no network I/O)
        initialize_database(settings)

        # Verify DB connectivity on startup with exponential backoff retry loop
        max_attempts = 3
        backoff = 0.5

        for attempt in range(1, max_attempts + 1):
            try:
                sessionmaker = get_sessionmaker()
                async with sessionmaker() as session:
                    await asyncio.wait_for(session.execute(text("SELECT 1")), timeout=2.0)
                logger.info("Database connectivity verified successfully at startup.")
                break
            except Exception as exc:
                if attempt == max_attempts:
                    logger.error(
                        "Database startup connectivity check failed after %d attempts: %s. Continuing startup...",
                        max_attempts,
                        exc,
                    )
                else:
                    sleep_time = backoff * (2 ** (attempt - 1))
                    logger.warning(
                        "Database startup connectivity check failed on attempt %d/%d, retrying in %.2fs: %s",
                        attempt,
                        max_attempts,
                        sleep_time,
                        exc,
                    )
                    await asyncio.sleep(sleep_time)

        # Still register lifecycle hooks for metadata/backwards compatibility
        register_lifecycle_hooks(app, settings)
        app.state.settings = settings

        # Verify Ollama availability and model existence on startup
        try:
            from app.llm.health import verify_ollama_status

            available, model_exists = await verify_ollama_status(settings)
            if not available:
                logger.warning(
                    "Ollama service is unreachable at %s. Backend remains operational but LLM calls will fail.",
                    settings.ollama.host,
                )
            elif not model_exists:
                logger.warning(
                    "WARNING: Configured Ollama model '%s' is missing on the Ollama server at %s. "
                    "Please pull the model manually by running:\n"
                    "docker exec -it ollama ollama pull %s",
                    settings.ollama.model,
                    settings.ollama.host,
                    settings.ollama.model,
                )
            else:
                logger.info(
                    "Ollama service is available and model '%s' is ready.",
                    settings.ollama.model,
                )
        except Exception as exc:
            logger.warning(
                "Unexpected error during Ollama startup verification: %s. Continuing startup...",
                exc,
            )

        yield
    finally:
        # Explicit shutdown sequence: Database engine first, then Redis client
        logger.info("Executing graceful lifespan shutdown sequence...")

        logger.info("Shutting down database engine...")
        try:
            await dispose_database()
        except Exception as exc:
            logger.error("Failed to dispose database engine during shutdown: %s", exc)

        logger.info("Shutting down Redis client...")
        try:
            await close_redis()
        except Exception as exc:
            logger.error("Failed to close Redis client during shutdown: %s", exc)

        try:
            from app.llm.client import close_shared_http_client

            await close_shared_http_client()
        except Exception as exc:
            logger.error("Failed to close LLM HTTP client during shutdown: %s", exc)


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
        """Return database readiness by executing SELECT 1 with retry and strict timeout."""
        import asyncio
        from sqlalchemy.exc import DBAPIError, OperationalError

        max_attempts = 3
        backoff = 0.5

        for attempt in range(1, max_attempts + 1):
            try:
                await asyncio.wait_for(session.execute(text("SELECT 1")), timeout=2.0)
                return DbHealthResponse(status="ok")
            except (OperationalError, DBAPIError, asyncio.TimeoutError) as exc:
                try:
                    await session.rollback()
                except Exception:
                    pass
                if attempt == max_attempts:
                    logging.getLogger(__name__).error(
                        "Database health check failed after %d attempts: %s",
                        max_attempts,
                        exc,
                    )
                    return DbHealthResponse(status="error", detail=str(exc))
                sleep_time = backoff * (2 ** (attempt - 1))
                await asyncio.sleep(sleep_time)
            except Exception as exc:
                try:
                    await session.rollback()
                except Exception:
                    pass
                logging.getLogger(__name__).error(
                    "Unexpected database health check failure: %s", exc
                )
                return DbHealthResponse(status="error", detail=str(exc))

    @app.get("/health/redis", response_model=RedisHealthResponse, response_model_exclude_none=True)
    async def health_redis(redis: Redis = Depends(get_redis)) -> RedisHealthResponse:
        """Return Redis readiness by issuing PING with strict timeout."""
        import asyncio

        try:
            await asyncio.wait_for(redis.ping(), timeout=2.0)
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
    from app.llm.client import register_hooks as register_llm_hooks

    register_db_hooks(app, settings)
    register_redis_hooks(app, settings)
    register_llm_hooks(app, settings)
    app.state.lifecycle_hooks_registered = True
    app.state.lifecycle_settings = settings
