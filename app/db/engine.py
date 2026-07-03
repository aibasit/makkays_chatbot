"""Async SQLAlchemy engine, session management, and migration entrypoints."""

from __future__ import annotations

import logging
import subprocess
import sys
from collections.abc import AsyncGenerator
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import Settings

logger = logging.getLogger(__name__)

_async_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def validate_asyncpg_url(database_url: str) -> None:
    """Validate that a database URL uses the required asyncpg scheme."""
    if not database_url.startswith("postgresql+asyncpg://"):
        raise ValueError("SUPABASE_DB_URL must use the postgresql+asyncpg:// scheme")


def create_engine(settings: Settings) -> AsyncEngine:
    """Create the configured async SQLAlchemy engine without connecting."""
    database_url = settings.db.supabase_db_url_async.get_secret_value()
    validate_asyncpg_url(database_url)
    parsed = urlparse(database_url)
    redacted_host = parsed.hostname or "<unknown>"
    logger.info("Creating async database engine host=%s pool_size=5 max_overflow=5", redacted_host)
    return create_async_engine(
        database_url,
        pool_size=5,
        max_overflow=5,
        pool_pre_ping=True,
    )


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create the async session factory used by request dependencies."""
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
        autocommit=False,
    )


def initialize_database(settings: Settings) -> AsyncEngine:
    """Initialize the process-wide database engine and session factory."""
    global _async_engine, _sessionmaker
    if _async_engine is None:
        _async_engine = create_engine(settings)
        _sessionmaker = create_sessionmaker(_async_engine)
    return _async_engine


def get_engine() -> AsyncEngine:
    """Return the initialized async engine."""
    if _async_engine is None:
        raise RuntimeError("Database engine has not been initialized")
    return _async_engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Return the initialized async session factory."""
    if _sessionmaker is None:
        raise RuntimeError("Database sessionmaker has not been initialized")
    return _sessionmaker


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async DB session that commits, rolls back, and closes safely."""
    session = get_sessionmaker()()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def dispose_database() -> None:
    """Dispose the async engine and reset database globals."""
    global _async_engine, _sessionmaker
    if _async_engine is not None:
        logger.info("Disposing async database engine")
        await _async_engine.dispose()
    _async_engine = None
    _sessionmaker = None


def register_hooks(app: FastAPI, settings: Settings) -> None:
    """Register database startup and shutdown hooks with Module 01 lifecycle."""
    initialize_database(settings)
    shutdown_hooks = getattr(app.state, "shutdown_hooks", [])
    shutdown_hooks.append(dispose_database)
    app.state.shutdown_hooks = shutdown_hooks


def run_migrations() -> None:
    """Run Alembic migrations with `alembic upgrade head`."""
    project_root = Path(__file__).resolve().parents[2]
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=project_root,
        check=True,
    )


def make_migration_engine(database_url: str) -> AsyncEngine:
    """Create a migration-only engine for Alembic."""
    validate_asyncpg_url(database_url)
    return create_async_engine(database_url, poolclass=NullPool)

