"""Unit tests for Module 07 Task Planner."""

from __future__ import annotations

import uuid

import pytest

from app.flags.schemas import FeatureFlags
from app.planner.exceptions import UnknownIntentError
from app.planner.planner import TaskPlanner
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


def test_build_plan_unknown_intent_raises() -> None:
    planner = TaskPlanner()

    with pytest.raises(UnknownIntentError):
        planner.build_plan(_intent("product_comparison"), _facts(), _state(), FeatureFlags())


def test_build_plan_never_returns_empty_steps() -> None:
    planner = TaskPlanner()

    plan = planner.build_plan(
        _intent("quote_request"), _facts(), _state(), FeatureFlags(enable_quotes=False)
    )

    assert len(plan.steps) > 0
    assert plan.steps[-1] == "respond"
