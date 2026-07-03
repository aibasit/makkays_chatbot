"""Helpers for building Ollama-compatible tool schemas."""

from __future__ import annotations

from typing import Any


def build_tool_schema(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    """Build the function tool payload expected by Ollama chat."""
    if not name.strip():
        raise ValueError("Tool name is required")
    if not description.strip():
        raise ValueError("Tool description is required")
    if not isinstance(parameters, dict):
        raise TypeError("Tool parameters must be a JSON schema object")
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }
