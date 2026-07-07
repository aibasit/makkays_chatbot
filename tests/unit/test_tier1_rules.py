"""Unit tests for Module 06 Tier 1 deterministic rules."""

from __future__ import annotations

from app.router.rules import Tier1RuleEngine


def test_tier1_matches_unambiguous_keywords() -> None:
    engine = Tier1RuleEngine()

    result = engine.match("I'd like a quote for this switch")

    assert result is not None
    assert result.intent == "quote_request"
    assert result.confidence == 1.0
    assert result.source == "tier1"
    assert result.candidates == ["quote_request"]


def test_tier1_returns_none_on_ambiguous_message() -> None:
    engine = Tier1RuleEngine()

    result = engine.match("How much is this broken switch going to cost to fix?")

    assert result is None


def test_tier1_requires_two_hits_for_overlap_group_intents() -> None:
    engine = Tier1RuleEngine()

    # Single, isolated hit on a "min 2" intent must not fire confidently.
    result = engine.match("Do you have a substitute for this part?")

    assert result is None


def test_tier1_detect_spec_question() -> None:
    engine = Tier1RuleEngine()

    assert engine.detect_spec_question("What does PoE mean on this switch?") is True
    assert engine.detect_spec_question("I would like to buy ten switches") is False
