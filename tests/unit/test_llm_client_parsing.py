"""Unit tests for LLM client parsing and validation."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.llm.client import OllamaClient
from app.llm.exceptions import LLMMalformedOutputError
from app.llm.schemas import ChatMessage
from app.llm.tool_schema import build_tool_schema


class StubOllamaClient(OllamaClient):
    """Ollama client whose transport returns a controlled payload."""

    def __init__(self, raw_response: dict[str, Any]) -> None:
        self.raw_response = raw_response
        super().__init__(
            SimpleNamespace(
                ollama=SimpleNamespace(
                    host="http://ollama.test",
                    model="qwen2.5:3b",
                    timeout_seconds=5,
                    default_temperature=0.0,
                ),
            ),  # type: ignore[arg-type]
        )

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.raw_response


def _messages() -> list[ChatMessage]:
    return [
        ChatMessage(role="system", content="Classify intent."),
        ChatMessage(role="user", content="Need a switch."),
    ]


@pytest.mark.asyncio
async def test_chat_requires_leading_system_message() -> None:
    client = StubOllamaClient({"message": {"content": "ok"}})

    with pytest.raises(ValueError, match="exactly one system"):
        await client.chat([ChatMessage(role="user", content="hello")])

    with pytest.raises(ValueError, match="first message"):
        await client.chat(
            [
                ChatMessage(role="user", content="hello"),
                ChatMessage(role="system", content="system"),
            ],
        )


@pytest.mark.asyncio
async def test_structured_output_validates_against_schema() -> None:
    schema = {
        "type": "object",
        "properties": {
            "intent": {"type": "string"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["intent", "confidence"],
    }
    client = StubOllamaClient(
        {"message": {"content": '{"intent":"sales_inquiry","confidence":0.92}'}},
    )

    response = await client.chat(_messages(), response_format=schema)

    assert response.content == '{"intent":"sales_inquiry","confidence":0.92}'


@pytest.mark.asyncio
async def test_malformed_json_raises_llm_malformed_output_error() -> None:
    client = StubOllamaClient({"message": {"content": "not-json"}})

    with pytest.raises(LLMMalformedOutputError):
        await client.chat(_messages(), response_format={"type": "object"})


def test_tool_schema_builder_produces_valid_ollama_format() -> None:
    parameters = {
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    }

    schema = build_tool_schema("retrieve_products", "Search products.", parameters)

    assert schema == {
        "type": "function",
        "function": {
            "name": "retrieve_products",
            "description": "Search products.",
            "parameters": parameters,
        },
    }


@pytest.mark.asyncio
async def test_tool_call_arguments_validate_against_declared_schema() -> None:
    tool = build_tool_schema(
        "classify_intent",
        "Classify the user intent.",
        {
            "type": "object",
            "properties": {"confidence": {"type": "number"}},
            "required": ["confidence"],
        },
    )
    client = StubOllamaClient(
        {
            "message": {
                "tool_calls": [
                    {"function": {"name": "classify_intent", "arguments": {"confidence": "high"}}},
                ],
            },
        },
    )

    with pytest.raises(LLMMalformedOutputError):
        await client.chat(_messages(), tools=[tool])
