"""Pydantic schemas for session facts and conversation state."""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


FACT_FIELDS: tuple[str, ...] = (
    "budget",
    "company",
    "industry",
    "product_interest",
    "project_size",
    "location",
    "timeline",
    "is_decision_maker",
    "quantity",
    "contact_name",
    "contact_email",
    "contact_phone",
)

STATE_FIELDS: tuple[str, ...] = (
    "current_intent",
    "intent_confidence",
    "awaiting_clarification",
    "clarification_candidates",
    "clarification_rounds",
    "current_plan",
    "current_plan_step",
    "last_question",
    "spec_question_detected",
    "contact_info_captured",
    "handoff_target",
    "language_code",
    "language_override",
)


class FactsSchema(BaseModel):
    """Read model for durable facts."""

    model_config = ConfigDict(from_attributes=True)

    tenant_id: UUID
    session_id: str
    budget: Decimal | None = Field(default=None, ge=0)
    company: str | None = None
    industry: str | None = None
    product_interest: str | None = None
    project_size: str | None = None
    location: str | None = None
    timeline: str | None = None
    is_decision_maker: bool | None = None
    quantity: int | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None


class FactsUpdate(BaseModel):
    """Partial update model for durable facts."""

    budget: Decimal | None = Field(default=None, ge=0)
    company: str | None = None
    industry: str | None = None
    product_interest: str | None = None
    project_size: str | None = None
    location: str | None = None
    timeline: str | None = None
    is_decision_maker: bool | None = None
    quantity: int | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None

    def non_null_patch(self) -> dict[str, Any]:
        """Return changed fact values, ignoring nulls so facts are not erased accidentally."""
        return {
            key: value
            for key, value in self.model_dump(exclude_unset=True).items()
            if key in FACT_FIELDS and value is not None
        }


class ConversationStateSchema(BaseModel):
    """Read model for short-lived conversation flow state."""

    model_config = ConfigDict(from_attributes=True)

    tenant_id: UUID
    session_id: str
    current_intent: str | None = None
    intent_confidence: float | None = None
    awaiting_clarification: bool = False
    clarification_candidates: list[str] = Field(default_factory=list)
    clarification_rounds: int = Field(default=0, ge=0)
    current_plan: dict[str, Any] | None = None
    current_plan_step: int | None = Field(default=None, ge=0)
    last_question: str | None = None
    spec_question_detected: bool = False
    contact_info_captured: bool = False
    handoff_target: str | None = None
    language_code: str = "en"
    language_override: bool = False

    @field_validator("language_code", mode="before")
    @classmethod
    def default_language_code(cls, value: Any) -> str:
        """Treat missing ORM/default values as English."""
        return "en" if value is None else str(value)

    @field_validator("language_override", mode="before")
    @classmethod
    def default_language_override(cls, value: Any) -> bool:
        """Treat missing ORM/default values as no explicit override."""
        return False if value is None else bool(value)

    @model_validator(mode="after")
    def validate_current_plan_step(self) -> "ConversationStateSchema":
        """Ensure the active step points to an existing plan step when possible."""
        if self.current_plan_step is None or self.current_plan is None:
            return self
        steps = self.current_plan.get("steps")
        if isinstance(steps, list) and self.current_plan_step >= len(steps):
            raise ValueError("current_plan_step must be less than len(current_plan.steps)")
        return self


class ConversationStateUpdate(BaseModel):
    """Partial update model for short-lived conversation state."""

    current_intent: str | None = None
    intent_confidence: float | None = None
    awaiting_clarification: bool | None = None
    clarification_candidates: list[str] | None = None
    clarification_rounds: int | None = Field(default=None, ge=0)
    current_plan: dict[str, Any] | None = None
    current_plan_step: int | None = Field(default=None, ge=0)
    last_question: str | None = None
    spec_question_detected: bool | None = None
    contact_info_captured: bool | None = None
    handoff_target: str | None = None
    language_code: str | None = None
    language_override: bool | None = None

    @field_validator("current_plan_step")
    @classmethod
    def validate_step_with_patch_plan(cls, value: int | None, info: Any) -> int | None:
        """Validate patch-local plan steps when the patch includes both fields."""
        plan = info.data.get("current_plan") if hasattr(info, "data") else None
        if value is None or plan is None:
            return value
        steps = plan.get("steps") if isinstance(plan, dict) else None
        if isinstance(steps, list) and value >= len(steps):
            raise ValueError("current_plan_step must be less than len(current_plan.steps)")
        return value

    def patch(self) -> dict[str, Any]:
        """Return explicitly supplied state values, preserving explicit null clears."""
        return {
            key: value
            for key, value in self.model_dump(exclude_unset=True).items()
            if key in STATE_FIELDS
        }
