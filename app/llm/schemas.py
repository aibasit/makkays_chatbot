"""Typed schemas and protocol for the LLM engine."""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    """Chat message sent to Ollama."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str | None = None


class ToolCall(BaseModel):
    """Tool call requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """Tool result message sent after executing a requested tool call."""

    role: Literal["tool"] = "tool"
    content: str
    tool_call_id: str


class LLMResponse(BaseModel):
    """Parsed LLM response returned to callers."""

    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class StructuredOutputRequest(BaseModel):
    """Structured output request payload used by classifier/explainer callers."""

    model_config = ConfigDict(populate_by_name=True)

    output_schema: dict[str, Any] = Field(alias="schema")
    messages: list[ChatMessage]


class ContextBuildMetadata(BaseModel):
    """Metadata describing context truncation and included references."""

    included_turn_count: int = 0
    included_source_ids: list[str] = Field(default_factory=list)
    truncated_turn_count: int = 0
    truncated_source_count: int = 0
    prompt_refs: dict[str, str] = Field(default_factory=dict)


class LLMClientProtocol(Protocol):
    """Structural protocol for all LLM clients."""

    async def chat(
        self,
        messages: list[ChatMessage],
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Run one chat completion call."""
        ...
