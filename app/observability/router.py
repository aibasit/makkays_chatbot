"""FastAPI endpoints for metrics and readiness."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from redis.asyncio import Redis
from sqlalchemy import text

from app.cache.redis_client import get_redis
from app.config import Settings
from app.db.engine import get_sessionmaker
from app.dependencies import get_settings
from app.observability.schemas import ReadyResponse

router = APIRouter(tags=["observability"])


@router.get("/metrics")
async def metrics() -> Response:
    """Return Prometheus text exposition for the in-process registry."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/ready", response_model=ReadyResponse)
async def ready(
    response: Response,
    settings: Settings = Depends(get_settings),
    redis: Redis = Depends(get_redis),
) -> ReadyResponse:
    """Return dependency readiness for DB, Redis, and the active LLM provider."""
    checks = await readiness_checks(settings, redis)
    is_ready = all(checks.values())
    response.status_code = status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadyResponse(status="ready" if is_ready else "not_ready", checks=checks)


async def readiness_checks(settings: Settings, redis: Redis) -> dict[str, bool]:
    """Run readiness checks independently so one failure does not mask another."""
    llm_key = settings.llm_provider
    db_ok, redis_ok, llm_ok = await asyncio.gather(
        check_db_ready(),
        check_redis_ready(redis),
        check_llm_ready(settings),
    )
    return {"db": db_ok, "redis": redis_ok, llm_key: llm_ok}


async def check_db_ready() -> bool:
    """Check database connectivity with a strict timeout."""
    try:
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            await asyncio.wait_for(session.execute(text("SELECT 1")), timeout=2.0)
    except Exception:
        return False
    return True


async def check_redis_ready(redis: Redis) -> bool:
    """Check Redis connectivity with a strict timeout."""
    try:
        await asyncio.wait_for(redis.ping(), timeout=2.0)
    except Exception:
        return False
    return True


async def check_llm_ready(settings: Settings) -> bool:
    """Check the active LLM provider without running inference."""
    try:
        if settings.llm_provider == "ollama":
            url = f"{settings.ollama.host.rstrip('/')}/api/tags"
            headers: dict[str, str] = {}
            timeout = 3.0
        else:
            url = f"{settings.groq.base_url.rstrip('/')}/models"
            headers = {"Authorization": f"Bearer {settings.groq.api_key.get_secret_value()}"}
            timeout = min(3.0, settings.groq.timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            _consume_json_if_possible(response)
    except Exception:
        return False
    return True


def _consume_json_if_possible(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None
