"""Integration tests for local Ollama roundtrips."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from app.dependencies import get_settings
from app.llm.client import OllamaClient, close_shared_http_client
from app.llm.exceptions import LLMTimeoutError
from app.llm.schemas import ChatMessage
from app.llm.tool_schema import build_tool_schema


async def _require_ollama_model() -> None:
    settings = get_settings()
    from app.llm.health import verify_ollama_status

    available, model_exists = await verify_ollama_status(settings)
    if not available:
        pytest.skip(f"Ollama is unavailable at {settings.ollama.host}")
    if not model_exists:
        pytest.skip(f"Ollama model {settings.ollama.model} is not installed")


def _messages(prompt: str) -> list[ChatMessage]:
    return [
        ChatMessage(role="system", content="You are a concise test assistant."),
        ChatMessage(role="user", content=prompt),
    ]


@pytest.fixture(autouse=True)
async def _close_client_after_test() -> None:
    yield
    await close_shared_http_client()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_chat_roundtrip_against_local_ollama() -> None:
    await _require_ollama_model()
    client = OllamaClient(get_settings())

    response = await client.chat(_messages("Reply with exactly: ok"), temperature=0.0)

    assert response.raw
    assert response.content is not None or response.tool_calls


@pytest.mark.asyncio
async def test_tool_calling_roundtrip_returns_tool_calls() -> None:
    await _require_ollama_model()
    client = OllamaClient(get_settings())
    tool = build_tool_schema(
        "classify_intent",
        "Classify the user's request.",
        {
            "type": "object",
            "properties": {
                "intent": {"type": "string"},
                "confidence": {"type": "number"},
            },
            "required": ["intent", "confidence"],
        },
    )

    response = await client.chat(
        _messages("Use the classify_intent tool for: I need pricing for a Cisco switch."),
        tools=[tool],
        temperature=0.0,
    )

    assert response.tool_calls
    assert response.tool_calls[0].name == "classify_intent"


@pytest.mark.asyncio
async def test_timeout_raises_llm_timeout_error() -> None:
    class SlowOllamaClient(OllamaClient):
        async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
            await asyncio.sleep(0.05)
            return {"message": {"content": "too late"}}

    client = SlowOllamaClient(
        SimpleNamespace(
            ollama=SimpleNamespace(
                host=get_settings().ollama.host,
                model=get_settings().ollama.model,
                timeout_seconds=0.001,
                default_temperature=0.0,
            ),
        ),  # type: ignore[arg-type]
    )

    with pytest.raises(LLMTimeoutError):
        await client.chat(_messages("timeout"))
