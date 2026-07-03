"""Redis client lifecycle and dependency provider."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from fastapi import FastAPI
from redis.asyncio import Redis

from app.config import Settings

logger = logging.getLogger(__name__)

_redis_client: Redis | None = None


def validate_redis_url(redis_url: str) -> None:
    """Validate that a Redis URL includes an explicit database index."""
    parsed = urlparse(redis_url)
    if parsed.scheme not in {"redis", "rediss"}:
        raise ValueError("REDIS_URL must use redis:// or rediss://")
    if not parsed.path or parsed.path == "/":
        raise ValueError("REDIS_URL must include an explicit DB index such as /0")
    db_part = parsed.path.lstrip("/")
    if not db_part.isdigit():
        raise ValueError("REDIS_URL DB index must be numeric")


def initialize_redis(settings: Settings) -> Redis:
    """Initialize the singleton Redis client without performing network I/O."""
    global _redis_client
    if _redis_client is None:
        redis_url = settings.redis.redis_url.get_secret_value()
        validate_redis_url(redis_url)
        parsed = urlparse(redis_url)
        logger.info("Initializing Redis client host=%s db=%s", parsed.hostname, parsed.path.lstrip("/"))
        _redis_client = Redis.from_url(redis_url, decode_responses=True)
    return _redis_client


def get_redis() -> Redis:
    """Return the initialized Redis client."""
    if _redis_client is None:
        raise RuntimeError("Redis client has not been initialized")
    return _redis_client


async def close_redis() -> None:
    """Close the Redis client and reset the singleton."""
    global _redis_client
    if _redis_client is not None:
        logger.info("Closing Redis client")
        await _redis_client.aclose()
    _redis_client = None


def register_hooks(app: FastAPI, settings: Settings) -> None:
    """Register Redis startup and shutdown hooks with Module 01 lifecycle."""
    initialize_redis(settings)
    shutdown_hooks = getattr(app.state, "shutdown_hooks", [])
    shutdown_hooks.append(close_redis)
    app.state.shutdown_hooks = shutdown_hooks

