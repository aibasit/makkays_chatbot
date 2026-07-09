"""Public chat API for the embedded widget."""

from __future__ import annotations

import secrets
import time
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from redis.asyncio import Redis

from app.availability.dependencies import get_availability_service
from app.availability.schemas import AvailabilityResult
from app.cache.redis_client import get_redis
from app.config import Settings
from app.db.engine import get_sessionmaker
from app.dependencies import get_settings
from app.language.schemas import LanguageCode, LanguageSetRequest, LanguageSetResponse, SUPPORTED_LANGUAGES
from app.observability import registry as metrics
from app.orchestrator.orchestrator import Orchestrator
from app.session.schemas import ConversationStateUpdate
from app.session.service import SessionStateService

router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    """Incoming widget message."""

    message: str = Field(min_length=1)


class ChatResponse(BaseModel):
    """Response returned to the widget."""

    assistant_message: str
    session_id: str
    intent: str | None = None
    awaiting_clarification: bool = False


@router.post("/chat", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    request: Request,
    response: Response,
    x_site_api_key: str | None = Header(default=None, alias="X-Site-Api-Key"),
    accept_language: str | None = Header(default=None, alias="Accept-Language"),
    settings: Settings = Depends(get_settings),
    redis: Redis = Depends(get_redis),
) -> ChatResponse:
    """Authenticate, rate-limit, preserve session cookie, and run one turn."""
    started = time.perf_counter()
    check_site_api_key(x_site_api_key, settings)
    message = payload.message.strip()
    if not message:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="message must not be blank",
        )
    if len(message) > settings.site.max_message_length:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"message exceeds {settings.site.max_message_length} characters",
        )

    await enforce_chat_rate_limit(redis, x_site_api_key or "", settings)
    session_id = get_or_create_session_id(request, response, settings)
    try:
        result = await Orchestrator().on_turn(
            tenant_id=settings.db.default_tenant_id,
            session_id=session_id,
            message=message,
            language_hint=parse_accept_language(accept_language),
        )
        return ChatResponse(
            assistant_message=result.assistant_message,
            session_id=session_id,
            intent=result.intent,
            awaiting_clarification=result.awaiting_clarification,
        )
    finally:
        metrics.metrics_registry.observe_chat_latency(time.perf_counter() - started)


def check_site_api_key(api_key: str | None, settings: Settings) -> None:
    """Raise 401 unless the provided site key matches settings."""
    expected = settings.site.site_api_key.get_secret_value()
    if api_key is None or not secrets.compare_digest(api_key, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid site API key")


def get_or_create_session_id(request: Request, response: Response, settings: Settings) -> str:
    """Reuse the widget session cookie or set a new one."""
    session_id = request.cookies.get(settings.site.session_cookie_name)
    if session_id:
        return session_id
    session_id = uuid4().hex
    response.set_cookie(
        key=settings.site.session_cookie_name,
        value=session_id,
        httponly=True,
        secure=settings.site.session_cookie_secure,
        samesite=settings.site.session_cookie_samesite,  # type: ignore[arg-type]
        max_age=settings.session.conversation_state_ttl_seconds,
    )
    return session_id


async def enforce_chat_rate_limit(redis: Redis, api_key: str, settings: Settings) -> None:
    """Apply Module 15's per-site-key one-minute request limit."""
    window_key = f"rate_limit:{api_key}:{_current_window()}"
    count = await redis.incr(window_key)
    if count == 1:
        await redis.expire(window_key, 60)
    if count > settings.site.chat_rate_limit_per_minute:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")


@router.post("/chat/language", response_model=LanguageSetResponse)
async def set_chat_language(
    payload: LanguageSetRequest,
    x_site_api_key: str | None = Header(default=None, alias="X-Site-Api-Key"),
    settings: Settings = Depends(get_settings),
    redis: Redis = Depends(get_redis),
) -> LanguageSetResponse:
    """Explicitly set the session language preference."""
    check_site_api_key(x_site_api_key, settings)
    if not settings.flags.enable_multi_language:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Multi-language is disabled")
    await enforce_chat_rate_limit(redis, x_site_api_key or "", settings)

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db_session:
        service = SessionStateService(db_session, redis, settings)
        await service.update_conversation_state(
            settings.db.default_tenant_id,
            payload.session_id,
            ConversationStateUpdate(
                language_code=payload.language_code,
                language_override=True,
            ),
        )
        await db_session.commit()
    return LanguageSetResponse(language_code=payload.language_code)


@router.get("/products/{product_id}/availability", response_model=AvailabilityResult)
async def get_product_availability(
    product_id: UUID,
    x_site_api_key: str | None = Header(default=None, alias="X-Site-Api-Key"),
    settings: Settings = Depends(get_settings),
    redis: Redis = Depends(get_redis),
) -> AvailabilityResult:
    """Return product availability outside the chat pipeline."""
    check_site_api_key(x_site_api_key, settings)
    if not settings.flags.enable_availability_check:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Availability checks are disabled")
    await enforce_chat_rate_limit(redis, x_site_api_key or "", settings)

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db_session:
        service = get_availability_service(db_session, settings)
        return await service.check(product_id, settings.db.default_tenant_id)


def parse_accept_language(value: str | None) -> LanguageCode | None:
    """Parse a simple Accept-Language header into a supported primary code."""
    if not value:
        return None
    first = value.split(",", 1)[0].strip().lower()
    primary = first.split("-", 1)[0]
    return primary if primary in SUPPORTED_LANGUAGES else None  # type: ignore[return-value]


def _current_window() -> int:
    import time

    return int(time.time() // 60)
