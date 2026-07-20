"""Per-intent rule functions: `(facts, state, flags, intent_result) -> ordered steps`.

Every function must always return a non-empty list; `respond` is the guaranteed
fallback step so a plan is never left without a user-facing response.
"""

from __future__ import annotations

from app.flags.schemas import FeatureFlags
from app.quotes.schemas import quote_slots_complete
from app.session.schemas import ConversationStateSchema, FactsSchema
from app.shared.intent_context import IntentResult
from app.solution_builder.schemas import solution_slots_complete


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


def plan_human_handoff(
    facts: FactsSchema,
    state: ConversationStateSchema,
    flags: FeatureFlags,
    intent_result: IntentResult,
) -> list[str]:
    """Transfer the session to a human team."""
    steps = []
    if flags.enable_human_handoff:
        steps.append("initiate_handoff")
    steps.append("respond")
    assert steps, "plan_human_handoff must always return at least one step"
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


def plan_product_comparison(
    facts: FactsSchema,
    state: ConversationStateSchema,
    flags: FeatureFlags,
    intent_result: IntentResult,
) -> list[str]:
    """Compare two or more products already surfaced by retrieval."""
    steps = ["retrieve_products"]
    if flags.enable_product_comparison:
        steps.append("compare_products")
    steps.append("respond")
    assert steps, "plan_product_comparison must always return at least one step"
    return steps


def plan_product_compatibility(
    facts: FactsSchema,
    state: ConversationStateSchema,
    flags: FeatureFlags,
    intent_result: IntentResult,
) -> list[str]:
    """Check whether two products are compatible."""
    steps = ["retrieve_products"]
    if flags.enable_compatibility_check:
        steps.append("check_compatibility")
    steps.append("respond")
    assert steps, "plan_product_compatibility must always return at least one step"
    return steps


def plan_accessory_recommendation(
    facts: FactsSchema,
    state: ConversationStateSchema,
    flags: FeatureFlags,
    intent_result: IntentResult,
) -> list[str]:
    """Recommend accessories for a product already surfaced by retrieval."""
    steps = ["retrieve_products"]
    if flags.enable_accessory_recommendation:
        steps.append("recommend_accessories")
    steps.append("respond")
    assert steps, "plan_accessory_recommendation must always return at least one step"
    return steps


def plan_product_finder_by_problem(
    facts: FactsSchema,
    state: ConversationStateSchema,
    flags: FeatureFlags,
    intent_result: IntentResult,
) -> list[str]:
    """User describes a problem; NL search (inside retrieve_products) finds a fit."""
    steps = ["retrieve_products", "respond"]
    assert steps, "plan_product_finder_by_problem must always return at least one step"
    return steps


def plan_product_alternative(
    facts: FactsSchema,
    state: ConversationStateSchema,
    flags: FeatureFlags,
    intent_result: IntentResult,
) -> list[str]:
    """Find a replacement/alternative for a product already surfaced by retrieval."""
    steps = ["retrieve_products", "find_alternatives", "respond"]
    assert steps, "plan_product_alternative must always return at least one step"
    return steps


def plan_specification_explainer(
    facts: FactsSchema,
    state: ConversationStateSchema,
    flags: FeatureFlags,
    intent_result: IntentResult,
) -> list[str]:
    """Explain a technical term, grounded by retrieved docs when RAG is enabled.

    Also retrieves products (not just docs): a message asking for the exact
    specs of a named model (e.g. "what are the specifications of OH1005T10400S")
    reads, to the classifier, like "explain a spec term" and lands here rather
    than in `sales_inquiry` — found live when this plan's lack of a
    `retrieve_products` step meant `explain_specification` had zero product
    data to ground an answer in for an exact model-code question.
    """
    steps = []
    if flags.enable_rag:
        steps.append("retrieve_products")
        steps.append("retrieve_docs")
    steps.append("explain_specification")
    steps.append("respond")
    assert steps, "plan_specification_explainer must always return at least one step"
    return steps


def plan_product_recommendation_wizard(
    facts: FactsSchema,
    state: ConversationStateSchema,
    flags: FeatureFlags,
    intent_result: IntentResult,
) -> list[str]:
    """Guided multi-turn wizard: one question per turn until requirements are complete."""
    steps = []
    if flags.enable_wizard:
        steps.append("run_wizard")
    steps.append("respond")
    assert steps, "plan_product_recommendation_wizard must always return at least one step"
    return steps


def plan_use_case_recommendation(
    facts: FactsSchema,
    state: ConversationStateSchema,
    flags: FeatureFlags,
    intent_result: IntentResult,
) -> list[str]:
    """Build a solution from a seeded use-case profile (e.g. "school", "hospital")."""
    steps = []
    if flags.enable_use_case_recommendation:
        steps.append("build_use_case_solution")
    steps.append("respond")
    assert steps, "plan_use_case_recommendation must always return at least one step"
    return steps


def plan_solution_builder(
    facts: FactsSchema,
    state: ConversationStateSchema,
    flags: FeatureFlags,
    intent_result: IntentResult,
) -> list[str]:
    """Build a solution directly when requirements are already known; else start the wizard."""
    steps = []
    if flags.enable_solution_builder and solution_slots_complete(facts, state):
        steps.append("build_solution")
    elif flags.enable_wizard:
        steps.append("run_wizard")
    steps.append("respond")
    assert steps, "plan_solution_builder must always return at least one step"
    return steps


def plan_availability_inquiry(
    facts: FactsSchema,
    state: ConversationStateSchema,
    flags: FeatureFlags,
    intent_result: IntentResult,
) -> list[str]:
    """Check stock/availability for retrieved products."""
    steps = ["retrieve_products"]
    if flags.enable_availability_check:
        steps.append("check_availability")
    steps.append("respond")
    assert steps, "plan_availability_inquiry must always return at least one step"
    return steps


def plan_installation_guidance(
    facts: FactsSchema,
    state: ConversationStateSchema,
    flags: FeatureFlags,
    intent_result: IntentResult,
) -> list[str]:
    """How to install/set up a product, grounded in installation-guide docs."""
    steps = ["retrieve_docs", "respond"]
    assert steps, "plan_installation_guidance must always return at least one step"
    return steps


def plan_troubleshooting(
    facts: FactsSchema,
    state: ConversationStateSchema,
    flags: FeatureFlags,
    intent_result: IntentResult,
) -> list[str]:
    """A fault/error/not-working report that reads as spec/setup rather than existing support."""
    steps = ["retrieve_docs", "respond"]
    assert steps, "plan_troubleshooting must always return at least one step"
    return steps


def plan_warranty_information(
    facts: FactsSchema,
    state: ConversationStateSchema,
    flags: FeatureFlags,
    intent_result: IntentResult,
) -> list[str]:
    """Warranty/RMA/repair questions, grounded in warranty-doc retrieval."""
    steps = ["retrieve_docs", "respond"]
    assert steps, "plan_warranty_information must always return at least one step"
    return steps


def plan_pdf_documentation_search(
    facts: FactsSchema,
    state: ConversationStateSchema,
    flags: FeatureFlags,
    intent_result: IntentResult,
) -> list[str]:
    """Requests for a manual/datasheet/brochure — unfiltered doc retrieval."""
    steps = ["retrieve_docs", "respond"]
    assert steps, "plan_pdf_documentation_search must always return at least one step"
    return steps


RULE_REGISTRY = {
    "sales_inquiry": plan_sales_inquiry,
    "quote_request": plan_quote_request,
    "technical_support": plan_technical_support,
    "escalation_request": plan_escalation_request,
    "human_handoff": plan_human_handoff,
    "out_of_scope": plan_out_of_scope,
    "product_comparison": plan_product_comparison,
    "product_compatibility": plan_product_compatibility,
    "accessory_recommendation": plan_accessory_recommendation,
    "product_finder_by_problem": plan_product_finder_by_problem,
    "product_alternative": plan_product_alternative,
    "specification_explainer": plan_specification_explainer,
    "product_recommendation_wizard": plan_product_recommendation_wizard,
    "use_case_recommendation": plan_use_case_recommendation,
    "solution_builder": plan_solution_builder,
    "availability_inquiry": plan_availability_inquiry,
    "installation_guidance": plan_installation_guidance,
    "troubleshooting": plan_troubleshooting,
    "warranty_information": plan_warranty_information,
    "pdf_documentation_search": plan_pdf_documentation_search,
}
