"""Validation and parsing helpers shared by all LLM provider clients."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from jsonschema import ValidationError as JsonSchemaValidationError
from jsonschema import validate as validate_json_schema

from app.llm.exceptions import LLMMalformedOutputError
from app.llm.schemas import ChatMessage, ToolCall


def validate_messages(messages: list[ChatMessage]) -> None:
    """Ensure the message list has exactly one leading system message."""
    system_count = sum(1 for message in messages if message.role == "system")
    if system_count != 1:
        raise ValueError("messages must contain exactly one system message")
    if not messages or messages[0].role != "system":
        raise ValueError("first message must be the system message")


def parse_tool_call(raw_tool_call: dict[str, Any]) -> ToolCall:
    """Parse a provider tool-call payload into a typed ToolCall."""
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


def validate_structured_content(content: str | None, response_format: dict[str, Any]) -> None:
    """Ensure structured output content parses as JSON matching the given schema."""
    if content is None:
        raise LLMMalformedOutputError("Structured output response had no content")
    try:
        parsed = json.loads(content)
        validate_json_schema(instance=parsed, schema=response_format)
    except (json.JSONDecodeError, JsonSchemaValidationError) as exc:
        raise LLMMalformedOutputError("Structured output did not match schema") from exc


def validate_tool_calls(tool_calls: list[ToolCall], tools: list[dict[str, Any]]) -> None:
    """Ensure requested tool calls reference declared tools with valid arguments."""
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
