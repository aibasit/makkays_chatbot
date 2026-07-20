"""Regression tests for Orchestrator._assistant_message_from_results.

Real bug found via live testing: when the `respond` step failed (e.g. an LLM
429), the fallback used to surface an *earlier* successful step's internal
audit text (like `compare`'s "Found N candidate products to compare.")
directly to the user instead of a friendly error message.
"""

from __future__ import annotations

from app.orchestrator.orchestrator import _assistant_message_from_results
from app.tools.schemas import ToolExecutionResult


def test_returns_respond_output_when_respond_succeeds() -> None:
    results = [
        ToolExecutionResult(step="retrieve_products", success=True, result_summary="3 products retrieved"),
        ToolExecutionResult(step="compare", success=True, result_summary="Found 3 candidate products to compare."),
        ToolExecutionResult(step="respond", success=True, result_summary="Here are three great options for you."),
    ]

    assert _assistant_message_from_results(results) == "Here are three great options for you."


def test_falls_back_to_friendly_message_not_an_earlier_steps_audit_text_when_respond_fails() -> None:
    results = [
        ToolExecutionResult(step="retrieve_products", success=True, result_summary="3 products retrieved"),
        ToolExecutionResult(step="compare", success=True, result_summary="Found 3 candidate products to compare."),
        ToolExecutionResult(step="respond", success=False, result_summary="", error="Groq returned an error response"),
    ]

    message = _assistant_message_from_results(results)

    assert message == "I could not complete that request just now. Please try again with a little more detail."
    assert "candidate products to compare" not in message


def test_falls_back_to_friendly_message_when_respond_step_never_ran() -> None:
    results = [
        ToolExecutionResult(step="retrieve_products", success=True, result_summary="3 products retrieved"),
    ]

    message = _assistant_message_from_results(results)

    assert message == "I could not complete that request just now. Please try again with a little more detail."
