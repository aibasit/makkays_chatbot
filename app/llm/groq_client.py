"""Async Groq Cloud client for chat, tool calling, and structured outputs."""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.config import Settings
from app.dependencies import get_settings
from app.llm._shared import (
    parse_tool_call,
    validate_messages,
    validate_structured_content,
    validate_tool_calls,
)
from app.llm.exceptions import LLMMalformedOutputError, LLMTimeoutError, LLMUnavailableError
from app.llm.schemas import ChatMessage, LLMResponse
from app.logging_config import get_logger

logger = get_logger(__name__)

_shared_http_client: httpx.AsyncClient | None = None
_shared_client_key: tuple[str, float] | None = None


class GroqClient:
    """Thin async wrapper over Groq Cloud's OpenAI-compatible `/chat/completions` endpoint."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Send a chat request to Groq and parse the typed response."""
        validate_messages(messages)
        payload = self._build_payload(messages, tools, response_format, temperature)
        started_at = time.perf_counter()
        try:
            raw = await self._post(payload)
        except httpx.TimeoutException as exc:
            logger.warning(
                "groq_http_timeout",
                extra={
                    "endpoint": self.settings.groq.base_url,
                    "model": self.settings.groq.model,
                    "timeout_seconds": self.settings.groq.timeout_seconds,
                    "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
                },
            )
            raise LLMTimeoutError("Groq chat request timed out") from exc
        except httpx.RequestError as exc:
            logger.warning(
                "groq_unavailable",
                extra={
                    "endpoint": self.settings.groq.base_url,
                    "model": self.settings.groq.model,
                    "timeout_seconds": self.settings.groq.timeout_seconds,
                    "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
                },
            )
            raise LLMUnavailableError("Groq is unavailable") from exc
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "groq_http_error",
                extra={
                    "endpoint": self.settings.groq.base_url,
                    "model": self.settings.groq.model,
                    "status_code": exc.response.status_code,
                    "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
                },
            )
            raise LLMUnavailableError("Groq returned an error response") from exc

        response = _parse_response(raw)
        if tools:
            validate_tool_calls(response.tool_calls, tools)
        if response_format is not None:
            validate_structured_content(response.content, response_format)

        logger.info(
            "groq_chat_success",
            extra={
                "endpoint": self.settings.groq.base_url,
                "model": self.settings.groq.model,
                "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
                "timeout_seconds": self.settings.groq.timeout_seconds,
            },
        )
        return response

    def _build_payload(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None,
        response_format: dict[str, Any] | None,
        temperature: float,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.settings.groq.model,
            "messages": [_message_payload(message) for message in messages],
            "stream": False,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
        if response_format is not None:
            payload["response_format"] = {"type": "json_object"}
        return payload

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        client = get_shared_http_client(self.settings)
        response = await client.post(
            "/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {self.settings.groq.api_key.get_secret_value()}"},
        )
        response.raise_for_status()
        return response.json()


def get_shared_http_client(settings: Settings) -> httpx.AsyncClient:
    """Return the process-wide Groq HTTP client."""
    global _shared_http_client, _shared_client_key
    key = (settings.groq.base_url, settings.groq.timeout_seconds)
    if _shared_http_client is None or _shared_client_key != key:
        if _shared_http_client is not None and not _shared_http_client.is_closed:
            logger.warning("groq_http_client_recreated")
        _shared_http_client = httpx.AsyncClient(
            base_url=settings.groq.base_url.rstrip("/"),
            timeout=httpx.Timeout(
                connect=5.0, read=settings.groq.timeout_seconds, write=5.0, pool=2.0
            ),
        )
        _shared_client_key = key
    return _shared_http_client


async def close_shared_http_client() -> None:
    """Close the process-wide Groq HTTP client."""
    global _shared_http_client, _shared_client_key
    if _shared_http_client is not None:
        await _shared_http_client.aclose()
    _shared_http_client = None
    _shared_client_key = None


def register_hooks(app: Any, settings: Settings) -> None:
    """Register Groq shutdown hook with the app lifecycle."""
    shutdown_hooks = getattr(app.state, "shutdown_hooks", [])
    shutdown_hooks.append(close_shared_http_client)
    app.state.shutdown_hooks = shutdown_hooks


def _message_payload(message: ChatMessage) -> dict[str, Any]:
    return message.model_dump(exclude_none=True)


def _parse_response(raw: dict[str, Any]) -> LLMResponse:
    choices = raw.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMMalformedOutputError("Groq response missing choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise LLMMalformedOutputError("Groq response missing message object")
    content = message.get("content")
    tool_calls = [parse_tool_call(item) for item in message.get("tool_calls") or []]
    return LLMResponse(content=content if content != "" else None, tool_calls=tool_calls, raw=raw)
