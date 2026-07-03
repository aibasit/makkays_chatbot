"""Pydantic schemas for conversation turn auditing."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ConversationTurnCreate(BaseModel):
    """Validated payload inserted into the append-only turn log."""

    tenant_id: UUID
    session_id: str
    turn_number: int = Field(ge=1)
    user_message: str = Field(min_length=1)
    assistant_message: str | None = None
    intent: str | None = None
    intent_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    intent_source: str | None = None
    candidate_intents: list[str] = Field(default_factory=list)
    prompt_version: dict[str, Any] | None = None
    tool_calls: list[dict[str, Any]] | None = None

    @field_validator("user_message")
    @classmethod
    def user_message_must_not_be_blank(cls, value: str) -> str:
        """Reject blank user messages before they reach Postgres."""
        if not value.strip():
            raise ValueError("user_message is required")
        return value

    @field_validator("tool_calls")
    @classmethod
    def validate_tool_calls(cls, value: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        """Each tool call must be an object containing at least tool and args."""
        if value is None:
            return value
        for item in value:
            if not isinstance(item, dict) or "tool" not in item or "args" not in item:
                raise ValueError("tool_calls items must contain tool and args")
        return value


class ConversationTurnRead(ConversationTurnCreate):
    """Read model for internal debugging/context assembly."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
