"""Unit tests for Groq client parsing and validation."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.llm.exceptions import LLMMalformedOutputError
from app.llm.groq_client import GroqClient
from app.llm.schemas import ChatMessage


class StubGroqClient(GroqClient):
    """Groq client whose transport returns a controlled payload."""

    def __init__(self, raw_response: dict[str, Any]) -> None:
        self.raw_response = raw_response
        super().__init__(
            SimpleNamespace(
                groq=SimpleNamespace(
                    api_key=SimpleNamespace(get_secret_value=lambda: "test-key"),
                    base_url="https://api.groq.test/openai/v1",
                    model="llama-3.3-70b-versatile",
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


def _choice(message: dict[str, Any]) -> dict[str, Any]:
    return {"choices": [{"message": message}]}


@pytest.mark.asyncio
async def test_chat_requires_leading_system_message() -> None:
    client = StubGroqClient(_choice({"content": "ok"}))

    with pytest.raises(ValueError, match="exactly one system"):
        await client.chat([ChatMessage(role="user", content="hello")])


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
    client = StubGroqClient(
        _choice({"content": '{"intent":"sales_inquiry","confidence":0.92}'}),
    )

    response = await client.chat(_messages(), response_format=schema)

    assert response.content == '{"intent":"sales_inquiry","confidence":0.92}'


@pytest.mark.asyncio
async def test_malformed_json_raises_llm_malformed_output_error() -> None:
    client = StubGroqClient(_choice({"content": "not-json"}))

    with pytest.raises(LLMMalformedOutputError):
        await client.chat(_messages(), response_format={"type": "object"})


@pytest.mark.asyncio
async def test_tool_call_arguments_parsed_from_json_string() -> None:
    client = StubGroqClient(
        _choice(
            {
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_123",
                        "function": {
                            "name": "classify_intent",
                            "arguments": '{"confidence": 0.9}',
                        },
                    },
                ],
            },
        ),
    )

    response = await client.chat(_messages())

    assert response.tool_calls[0].name == "classify_intent"
    assert response.tool_calls[0].arguments == {"confidence": 0.9}
    assert response.tool_calls[0].id == "call_123"


@pytest.mark.asyncio
async def test_missing_choices_raises_llm_malformed_output_error() -> None:
    client = StubGroqClient({"choices": []})

    with pytest.raises(LLMMalformedOutputError):
        await client.chat(_messages())
