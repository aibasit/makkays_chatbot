"""Prompt reference schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

PromptCategory = Literal[
    "system",
    "classification",
    "rag",
    "clarification",
    "tools",
    "quotes",
    "translation",
]


class PromptRef(BaseModel):
    """Reference to one exact versioned prompt file."""

    category: PromptCategory
    name: str
    version: str


class PromptVersionTag:
    """Builder for the `conversation_turns.prompt_version` JSON object.

    Callers record one entry per prompt they used this turn, e.g.
    `{"system": "base_v1", "intent": "classify_intent_v1"}`, then pass the result
    to Module 04's `record_turn`.
    """

    def __init__(self) -> None:
        self._entries: dict[str, str] = {}

    def add(self, key: str, ref: PromptRef) -> "PromptVersionTag":
        """Record which prompt ref was used under `key` (e.g. "system", "intent")."""
        self._entries[key] = f"{ref.name}_v{ref.version}"
        return self

    def to_dict(self) -> dict[str, str]:
        """Return the assembled tag as a plain dict, ready for `record_turn`."""
        return dict(self._entries)
