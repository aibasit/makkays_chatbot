"""Per-intent rule functions: `(facts, state, flags, intent_result) -> ordered steps`.

Every function must always return a non-empty list; `respond` is the guaranteed
fallback step so a plan is never left without a user-facing response.
"""

from __future__ import annotations

from app.flags.schemas import FeatureFlags
from app.quotes.schemas import quote_slots_complete
from app.session.schemas import ConversationStateSchema, FactsSchema
from app.shared.intent_context import IntentResult


def contact_info_newly_captured(state: ConversationStateSchema) -> bool:
    """Return whether contact info was captured for the first time this session."""
    return state.contact_info_captured is True


def plan_sales_inquiry(
    facts: FactsSchema,
    state: ConversationStateSchema,
    flags: FeatureFlags,
    intent_result: IntentResult,
) -> list[str]:
    """Product discovery/recommendation intent."""
    steps = ["retrieve_products"]
    if intent_result.spec_question_detected:
        steps.append("retrieve_docs")
    if len(intent_result.candidates) > 1:
        steps.append("compare")
    if flags.enable_quotes and quote_slots_complete(facts, state):
        steps.append("generate_quote")
    elif (
        flags.enable_quotes
        and not quote_slots_complete(facts, state)
        and intent_result.intent == "quote_request"
    ):
        steps.append("request_missing_slots")
    if flags.enable_crm and contact_info_newly_captured(state):
        steps.append("create_lead")
    steps.append("respond")
    assert steps, "plan_sales_inquiry must always return at least one step"
    return steps


def plan_quote_request(
    facts: FactsSchema,
    state: ConversationStateSchema,
    flags: FeatureFlags,
    intent_result: IntentResult,
) -> list[str]:
    """Explicit pricing/quotation intent."""
    if flags.enable_quotes and quote_slots_complete(facts, state):
        steps = ["retrieve_products", "generate_quote", "respond"]
    else:
        steps = ["retrieve_products", "request_missing_slots", "respond"]
    assert steps, "plan_quote_request must always return at least one step"
    return steps


def plan_technical_support(
    facts: FactsSchema,
    state: ConversationStateSchema,
    flags: FeatureFlags,
    intent_result: IntentResult,
) -> list[str]:
    """Existing-product fault/setup/troubleshooting intent."""
    steps = ["retrieve_docs", "respond"]
    assert steps, "plan_technical_support must always return at least one step"
    return steps


def plan_escalation_request(
    facts: FactsSchema,
    state: ConversationStateSchema,
    flags: FeatureFlags,
    intent_result: IntentResult,
) -> list[str]:
    """User asked for a human, or clarification exceeded its maximum rounds."""
    steps = ["respond"]
    assert steps, "plan_escalation_request must always return at least one step"
    return steps


def plan_out_of_scope(
    facts: FactsSchema,
    state: ConversationStateSchema,
    flags: FeatureFlags,
    intent_result: IntentResult,
) -> list[str]:
    """Request unrelated to supported sales/support work."""
    steps = ["respond"]
    assert steps, "plan_out_of_scope must always return at least one step"
    return steps


RULE_REGISTRY = {
    "sales_inquiry": plan_sales_inquiry,
    "quote_request": plan_quote_request,
    "technical_support": plan_technical_support,
    "escalation_request": plan_escalation_request,
    "out_of_scope": plan_out_of_scope,
}
