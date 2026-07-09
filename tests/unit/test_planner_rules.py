"""Unit tests for Module 07 Task Planner."""

from __future__ import annotations

import uuid

from app.config import INTENT_TAXONOMY
from app.flags.schemas import FeatureFlags
from app.planner.planner import TaskPlanner
from app.planner.rules import RULE_REGISTRY
from app.session.schemas import ConversationStateSchema, FactsSchema
from app.shared.intent_context import IntentResult


def _facts(**overrides: object) -> FactsSchema:
    return FactsSchema(tenant_id=uuid.uuid4(), session_id="s1", **overrides)


def _state(**overrides: object) -> ConversationStateSchema:
    return ConversationStateSchema(tenant_id=uuid.uuid4(), session_id="s1", **overrides)


def _intent(intent: str, **overrides: object) -> IntentResult:
    return IntentResult(intent=intent, confidence=0.9, source="tier2", **overrides)


def test_plan_sales_inquiry_no_product_identified_includes_retrieve_products() -> None:
    planner = TaskPlanner()

    plan = planner.build_plan(_intent("sales_inquiry"), _facts(), _state(), FeatureFlags())

    assert plan.steps[0] == "retrieve_products"
    assert plan.steps[-1] == "respond"


def test_plan_sales_inquiry_rag_flag_off_skips_retrieve_docs() -> None:
    planner = TaskPlanner()
    intent_result = _intent("sales_inquiry", spec_question_detected=True)

    plan = planner.build_plan(intent_result, _facts(), _state(), FeatureFlags(enable_rag=False))

    assert "retrieve_docs" not in plan.steps


def test_plan_sales_inquiry_multiple_candidates_includes_compare() -> None:
    planner = TaskPlanner()
    intent_result = _intent("sales_inquiry", candidates=["sales_inquiry", "quote_request"])

    plan = planner.build_plan(intent_result, _facts(), _state(), FeatureFlags())

    assert "compare" in plan.steps


def test_plan_sales_inquiry_quote_slots_complete_includes_generate_quote() -> None:
    planner = TaskPlanner()
    facts = _facts(company="Acme", product_interest="switch", quantity=5, budget=1000)

    plan = planner.build_plan(_intent("sales_inquiry"), facts, _state(), FeatureFlags())

    assert "generate_quote" in plan.steps


def test_plan_quote_request_quote_slots_incomplete_includes_request_missing_slots() -> None:
    planner = TaskPlanner()

    plan = planner.build_plan(_intent("quote_request"), _facts(), _state(), FeatureFlags())

    assert plan.steps == ["retrieve_products", "request_missing_slots", "respond"]


def test_plan_quote_request_quote_slots_complete_includes_generate_quote() -> None:
    planner = TaskPlanner()
    facts = _facts(company="Acme", product_interest="switch", quantity=5, budget=1000)

    plan = planner.build_plan(_intent("quote_request"), facts, _state(), FeatureFlags())

    assert plan.steps == ["retrieve_products", "generate_quote", "respond"]


def test_plan_sales_inquiry_create_lead_when_contact_newly_captured() -> None:
    planner = TaskPlanner()
    state = _state(contact_info_captured=True)

    plan = planner.build_plan(_intent("sales_inquiry"), _facts(), state, FeatureFlags())

    assert "create_lead" in plan.steps


def test_plan_sales_inquiry_fallback_is_respond_when_nothing_else_matches() -> None:
    planner = TaskPlanner()

    plan = planner.build_plan(
        _intent("sales_inquiry"), _facts(), _state(), FeatureFlags(enable_quotes=False, enable_crm=False)
    )

    assert plan.steps == ["retrieve_products", "respond"]


def test_plan_technical_support_always_retrieve_docs_then_respond() -> None:
    planner = TaskPlanner()

    plan = planner.build_plan(_intent("technical_support"), _facts(), _state(), FeatureFlags())

    assert plan.steps == ["retrieve_docs", "respond"]


def test_plan_escalation_request_is_single_respond_step() -> None:
    planner = TaskPlanner()

    plan = planner.build_plan(_intent("escalation_request"), _facts(), _state(), FeatureFlags())

    assert plan.steps == ["respond"]


def test_plan_out_of_scope_is_single_respond_step() -> None:
    planner = TaskPlanner()

    plan = planner.build_plan(_intent("out_of_scope"), _facts(), _state(), FeatureFlags())

    assert plan.steps == ["respond"]


def test_plan_human_handoff_routes_to_initiate_handoff() -> None:
    planner = TaskPlanner()

    plan = planner.build_plan(_intent("human_handoff"), _facts(), _state(), FeatureFlags())

    assert plan.steps == ["initiate_handoff", "respond"]


def test_plan_human_handoff_flag_off_falls_back_to_respond() -> None:
    planner = TaskPlanner()

    plan = planner.build_plan(
        _intent("human_handoff"),
        _facts(),
        _state(),
        FeatureFlags(enable_human_handoff=False),
    )

    assert plan.steps == ["respond"]


def test_plan_human_handoff_is_no_longer_unknown() -> None:
    planner = TaskPlanner()

    # "human_handoff" is real (v4.2 taxonomy) but its Planner rule isn't owned by
    # any module built so far — a genuinely unregistered intent, unlike
    # "product_comparison" which Module 18 registered a rule for.
    plan = planner.build_plan(_intent("human_handoff"), _facts(), _state(), FeatureFlags())

    assert plan.steps[0] == "initiate_handoff"


def test_plan_availability_inquiry_routes_to_check_availability() -> None:
    planner = TaskPlanner()

    plan = planner.build_plan(
        _intent("availability_inquiry"),
        _facts(),
        _state(),
        FeatureFlags(enable_availability_check=True),
    )

    assert plan.steps == ["retrieve_products", "check_availability", "respond"]


def test_plan_availability_inquiry_flag_off_skips_check() -> None:
    planner = TaskPlanner()

    plan = planner.build_plan(
        _intent("availability_inquiry"),
        _facts(),
        _state(),
        FeatureFlags(enable_availability_check=False),
    )

    assert plan.steps == ["retrieve_products", "respond"]


def test_plan_product_recommendation_wizard_routes_to_run_wizard() -> None:
    planner = TaskPlanner()

    plan = planner.build_plan(_intent("product_recommendation_wizard"), _facts(), _state(), FeatureFlags())

    assert plan.steps == ["run_wizard", "respond"]


def test_plan_product_recommendation_wizard_flag_off_skips_run_wizard() -> None:
    planner = TaskPlanner()

    plan = planner.build_plan(
        _intent("product_recommendation_wizard"), _facts(), _state(), FeatureFlags(enable_wizard=False)
    )

    assert plan.steps == ["respond"]


def test_plan_use_case_recommendation_routes_to_build_use_case_solution() -> None:
    planner = TaskPlanner()

    plan = planner.build_plan(_intent("use_case_recommendation"), _facts(), _state(), FeatureFlags())

    assert plan.steps == ["build_use_case_solution", "respond"]


def test_plan_solution_builder_slots_complete_routes_to_build_solution() -> None:
    planner = TaskPlanner()
    facts = _facts(product_interest="school deployment", quantity=200)

    plan = planner.build_plan(_intent("solution_builder"), facts, _state(), FeatureFlags())

    assert plan.steps == ["build_solution", "respond"]


def test_plan_solution_builder_slots_incomplete_falls_back_to_run_wizard() -> None:
    planner = TaskPlanner()

    plan = planner.build_plan(_intent("solution_builder"), _facts(), _state(), FeatureFlags())

    assert plan.steps == ["run_wizard", "respond"]


def test_plan_solution_builder_both_flags_off_is_respond_only() -> None:
    planner = TaskPlanner()
    facts = _facts(product_interest="school deployment", quantity=200)

    plan = planner.build_plan(
        _intent("solution_builder"),
        facts,
        _state(),
        FeatureFlags(enable_solution_builder=False, enable_wizard=False),
    )

    assert plan.steps == ["respond"]


def test_every_canonical_intent_has_a_registered_plan_rule() -> None:
    """Every intent the classifier can return must have a Planner rule.

    Regression test for a real production crash: `installation_guidance`,
    `troubleshooting`, `warranty_information`, and `pdf_documentation_search`
    were all part of the classifier's own intent taxonomy (and already had
    security policies allowing them) but had no RULE_REGISTRY entry — the
    classifier picking any of them crashed the turn with an unhandled
    UnknownIntentError and a raw 500, instead of any of pytest's fakes/mocks
    ever exercising the full taxonomy against the registry to catch it.
    """
    missing = [intent for intent in INTENT_TAXONOMY if intent not in RULE_REGISTRY]
    assert missing == []


def test_plan_installation_guidance_retrieves_docs() -> None:
    planner = TaskPlanner()

    plan = planner.build_plan(_intent("installation_guidance"), _facts(), _state(), FeatureFlags())

    assert plan.steps == ["retrieve_docs", "respond"]


def test_plan_troubleshooting_retrieves_docs() -> None:
    planner = TaskPlanner()

    plan = planner.build_plan(_intent("troubleshooting"), _facts(), _state(), FeatureFlags())

    assert plan.steps == ["retrieve_docs", "respond"]


def test_plan_warranty_information_retrieves_docs() -> None:
    planner = TaskPlanner()

    plan = planner.build_plan(_intent("warranty_information"), _facts(), _state(), FeatureFlags())

    assert plan.steps == ["retrieve_docs", "respond"]


def test_plan_pdf_documentation_search_retrieves_docs() -> None:
    planner = TaskPlanner()

    plan = planner.build_plan(_intent("pdf_documentation_search"), _facts(), _state(), FeatureFlags())

    assert plan.steps == ["retrieve_docs", "respond"]


def test_build_plan_never_returns_empty_steps() -> None:
    planner = TaskPlanner()

    plan = planner.build_plan(
        _intent("quote_request"), _facts(), _state(), FeatureFlags(enable_quotes=False)
    )

    assert len(plan.steps) > 0
    assert plan.steps[-1] == "respond"
