"""Tool execution schemas: security policy shape, execution results, and context."""

from __future__ import annotations

from typing import Literal, NamedTuple
from uuid import UUID

from pydantic import BaseModel, Field

from app.session.schemas import ConversationStateSchema, FactsSchema


class SecurityPolicySchema(BaseModel):
    """One tool's declarative security policy, parsed from its YAML file."""

    tool_name: str
    allowed_intents: list[str]
    required_state: list[str] = Field(default_factory=list)
    required_slots: list[str] = Field(default_factory=list)
    rate_limit: str | None = None
    audit_log: bool = False


class PolicyCheckResult(BaseModel):
    """Outcome of one Security Policy check."""

    allowed: bool
    reason: str | None = None
    clause_failed: Literal["intent", "state", "slots", "rate_limit"] | None = None


class ToolExecutionResult(BaseModel):
    """Result of running (or being denied for) one plan step."""

    step: str
    success: bool
    result_summary: str
    error: str | None = None
    product_ids: list[UUID] | None = None


class ExecutionContext(BaseModel):
    """Accumulates prior step results for the lifetime of one plan execution."""

    retrieve_products: ToolExecutionResult | None = None
    retrieve_docs: ToolExecutionResult | None = None
    generate_quote: ToolExecutionResult | None = None
    create_lead: ToolExecutionResult | None = None
    compare_products: ToolExecutionResult | None = None
    check_compatibility: ToolExecutionResult | None = None
    recommend_accessories: ToolExecutionResult | None = None
    find_alternatives: ToolExecutionResult | None = None
    explain_specification: ToolExecutionResult | None = None
    run_wizard: ToolExecutionResult | None = None
    build_use_case_solution: ToolExecutionResult | None = None
    build_solution: ToolExecutionResult | None = None
    initiate_handoff: ToolExecutionResult | None = None
    check_availability: ToolExecutionResult | None = None

    def get_product_ids(self) -> list[UUID] | None:
        """Return product IDs surfaced by `retrieve_products`, if it ran and succeeded."""
        result = self.retrieve_products
        return result.product_ids if result and result.success else None


class SessionContext(NamedTuple):
    """Read-only per-turn session data passed to every tool implementation."""

    tenant_id: UUID
    session_id: str
    facts: FactsSchema
    conversation_state: ConversationStateSchema
    # The current turn's raw user text. Defaults to "" for the many existing call
    # sites (tests, other tool modules) that only need tenant/session/facts/state;
    # tools that need the literal message this turn (e.g. the M19 wizard) read this.
    message: str = ""
