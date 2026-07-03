"""Async Ollama client for chat, tool calling, and structured outputs."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from uuid import uuid4

import httpx
from jsonschema import ValidationError as JsonSchemaValidationError
from jsonschema import validate as validate_json_schema

from app.config import Settings
from app.dependencies import get_settings
from app.llm.exceptions import LLMMalformedOutputError, LLMTimeoutError, LLMUnavailableError
from app.llm.schemas import ChatMessage, LLMResponse, ToolCall
from app.logging_config import get_logger

logger = get_logger(__name__)

_shared_http_client: httpx.AsyncClient | None = None
_shared_timeout_seconds: int | None = None


class OllamaClient:
    """Thin async wrapper over Ollama's `/api/chat` endpoint."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Send a chat request to Ollama and parse the typed response."""
        _validate_messages(messages)
        payload = self._build_payload(messages, tools, response_format, temperature)
        started_at = time.perf_counter()
        try:
            raw = await asyncio.wait_for(
                self._post(payload),
                timeout=self.settings.ollama.timeout_seconds,
            )
        except TimeoutError as exc:
            logger.warning(
                "ollama_chat_timeout",
                extra={
                    "endpoint": self.settings.ollama.host,
                    "model": self.settings.ollama.model,
                    "timeout_seconds": self.settings.ollama.timeout_seconds,
                    "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
                },
            )
            raise LLMTimeoutError("Ollama chat request timed out") from exc
        except httpx.TimeoutException as exc:
            logger.warning(
                "ollama_http_timeout",
                extra={
                    "endpoint": self.settings.ollama.host,
                    "model": self.settings.ollama.model,
                    "timeout_seconds": self.settings.ollama.timeout_seconds,
                    "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
                },
            )
            raise LLMTimeoutError("Ollama chat request timed out") from exc
        except httpx.RequestError as exc:
            logger.warning(
                "ollama_unavailable",
                extra={
                    "endpoint": self.settings.ollama.host,
                    "model": self.settings.ollama.model,
                    "timeout_seconds": self.settings.ollama.timeout_seconds,
                    "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
                },
            )
            raise LLMUnavailableError("Ollama is unavailable") from exc

        response = _parse_response(raw)
        if tools:
            _validate_tool_calls(response.tool_calls, tools)
        if response_format is not None:
            _validate_structured_content(response.content, response_format)

        logger.info(
            "ollama_chat_success",
            extra={
                "endpoint": self.settings.ollama.host,
                "model": self.settings.ollama.model,
                "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
                "timeout_seconds": self.settings.ollama.timeout_seconds,
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
            "model": self.settings.ollama.model,
            "messages": [_message_payload(message) for message in messages],
            "stream": False,
            "options": {"temperature": temperature},
        }
        if tools:
            payload["tools"] = tools
        if response_format is not None:
            payload["format"] = response_format
        return payload

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        client = get_shared_http_client(self.settings)
        response = await client.post("/api/chat", json=payload)
        response.raise_for_status()
        return response.json()


def get_shared_http_client(settings: Settings) -> httpx.AsyncClient:
    """Return the process-wide Ollama HTTP client."""
    global _shared_http_client, _shared_timeout_seconds
    timeout_seconds = settings.ollama.timeout_seconds
    if _shared_http_client is None or _shared_timeout_seconds != timeout_seconds:
        if _shared_http_client is not None and not _shared_http_client.is_closed:
            logger.warning("ollama_http_client_recreated")
        _shared_http_client = httpx.AsyncClient(
            base_url=settings.ollama.host.rstrip("/"),
            timeout=httpx.Timeout(connect=5.0, read=timeout_seconds, write=5.0, pool=2.0),
        )
        _shared_timeout_seconds = timeout_seconds
    return _shared_http_client


async def close_shared_http_client() -> None:
    """Close the process-wide Ollama HTTP client."""
    global _shared_http_client, _shared_timeout_seconds
    if _shared_http_client is not None:
        await _shared_http_client.aclose()
    _shared_http_client = None
    _shared_timeout_seconds = None


def register_hooks(app: Any, settings: Settings) -> None:
    """Register LLM shutdown hook with the app lifecycle."""
    shutdown_hooks = getattr(app.state, "shutdown_hooks", [])
    shutdown_hooks.append(close_shared_http_client)
    app.state.shutdown_hooks = shutdown_hooks


def _validate_messages(messages: list[ChatMessage]) -> None:
    system_count = sum(1 for message in messages if message.role == "system")
    if system_count != 1:
        raise ValueError("messages must contain exactly one system message")
    if not messages or messages[0].role != "system":
        raise ValueError("first message must be the system message")


def _message_payload(message: ChatMessage) -> dict[str, Any]:
    payload = message.model_dump(exclude_none=True)
    return payload


def _parse_response(raw: dict[str, Any]) -> LLMResponse:
    message = raw.get("message")
    if not isinstance(message, dict):
        raise LLMMalformedOutputError("Ollama response missing message object")
    content = message.get("content")
    tool_calls = [_parse_tool_call(item) for item in message.get("tool_calls") or []]
    return LLMResponse(content=content if content != "" else None, tool_calls=tool_calls, raw=raw)


def _parse_tool_call(raw_tool_call: dict[str, Any]) -> ToolCall:
    if not isinstance(raw_tool_call, dict):
        raise LLMMalformedOutputError("Tool call must be an object")
    function = raw_tool_call.get("function")
    if not isinstance(function, dict):
        raise LLMMalformedOutputError("Tool call missing function object")
    name = function.get("name")
    if not isinstance(name, str) or not name:
        raise LLMMalformedOutputError("Tool call missing function name")
    arguments = function.get("arguments") or {}
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError as exc:
            raise LLMMalformedOutputError("Tool call arguments are not valid JSON") from exc
    if not isinstance(arguments, dict):
        raise LLMMalformedOutputError("Tool call arguments must be an object")
    return ToolCall(id=str(raw_tool_call.get("id") or uuid4()), name=name, arguments=arguments)


def _validate_structured_content(content: str | None, response_format: dict[str, Any]) -> None:
    if content is None:
        raise LLMMalformedOutputError("Structured output response had no content")
    try:
        parsed = json.loads(content)
        validate_json_schema(instance=parsed, schema=response_format)
    except (json.JSONDecodeError, JsonSchemaValidationError) as exc:
        raise LLMMalformedOutputError("Structured output did not match schema") from exc


def _validate_tool_calls(tool_calls: list[ToolCall], tools: list[dict[str, Any]]) -> None:
    tool_schemas = {
        tool.get("function", {}).get("name"): tool.get("function", {}).get("parameters", {})
        for tool in tools
        if isinstance(tool, dict)
    }
    for tool_call in tool_calls:
        schema = tool_schemas.get(tool_call.name)
        if schema is None:
            raise LLMMalformedOutputError(f"Tool call requested undeclared tool {tool_call.name}")
        try:
            validate_json_schema(instance=tool_call.arguments, schema=schema)
        except JsonSchemaValidationError as exc:
            raise LLMMalformedOutputError("Tool call arguments did not match schema") from exc
