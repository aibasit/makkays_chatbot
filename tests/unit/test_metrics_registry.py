"""Unit tests for Module 16 MetricsRegistry."""

from __future__ import annotations

from unittest.mock import MagicMock

from prometheus_client import CollectorRegistry, generate_latest

from app.observability.registry import MetricsRegistry


def test_metrics_registry_increment_and_read_back() -> None:
    registry = CollectorRegistry()
    metrics = MetricsRegistry(registry)

    metrics.increment_intent_classification("tier1", "sales_inquiry")
    metrics.increment_rag_hit(True)
    metrics.increment_quote_result(True)
    metrics.increment_crm_sync_result(False)
    metrics.increment_lead_created()
    metrics.increment_tool_result("respond", True)
    metrics.observe_chat_latency(0.42)

    output = generate_latest(registry).decode("utf-8")
    assert 'intent_classification_total{intent="sales_inquiry",source="tier1"} 1.0' in output
    assert 'rag_hit_total{hit="true"} 1.0' in output
    assert 'quote_result_total{success="true"} 1.0' in output
    assert 'crm_sync_result_total{success="false"} 1.0' in output
    assert "lead_created_total 1.0" in output
    assert 'tool_result_total{success="true",tool_name="respond"} 1.0' in output
    assert "chat_latency_seconds_count 1.0" in output


def test_metrics_registry_confidence_histogram_buckets() -> None:
    registry = CollectorRegistry()
    metrics = MetricsRegistry(registry)

    metrics.record_intent_confidence(0.91)
    metrics.record_intent_confidence(2.0)

    output = generate_latest(registry).decode("utf-8")
    assert 'intent_confidence_histogram_bucket{le="0.9"} 0.0' in output
    assert 'intent_confidence_histogram_bucket{le="1.0"} 2.0' in output
    assert "intent_confidence_histogram_count 2.0" in output


def test_increment_lead_created_increments_correct_counter() -> None:
    registry = CollectorRegistry()
    metrics = MetricsRegistry(registry)

    metrics.increment_lead_created()
    metrics.increment_lead_created()

    output = generate_latest(registry).decode("utf-8")
    assert "lead_created_total 2.0" in output


def test_metrics_registry_is_no_op_when_patched_with_mock() -> None:
    metrics = MagicMock()

    metrics.increment_rag_hit(False)
    metrics.increment_quote_result(True)

    metrics.increment_rag_hit.assert_called_once_with(False)
    metrics.increment_quote_result.assert_called_once_with(True)


def test_v42_extension_metric_methods_exist_and_increment() -> None:
    registry = CollectorRegistry()
    metrics = MetricsRegistry(registry)

    metrics.increment_quote_pdf_generated(True)
    metrics.increment_comparison_request(False)
    metrics.increment_compatibility_check("rule", None)
    metrics.increment_accessory_recommendation(True)
    metrics.increment_solution_build("wizard")
    metrics.increment_wizard_session(False)
    metrics.increment_handoff_request("sales", "created")
    metrics.increment_language_detection("en")
    metrics.increment_translation_request("ur", True)
    metrics.increment_availability_check("local_db", False)

    output = generate_latest(registry).decode("utf-8")
    assert 'chatbot_quote_pdf_generated_total{success="true"} 1.0' in output
    assert 'chatbot_comparison_requests_total{success="false"} 1.0' in output
    assert 'chatbot_compatibility_checks_total{is_compatible="unknown",source="rule"} 1.0' in output
    assert 'chatbot_availability_checks_total{in_stock="false",source="local_db"} 1.0' in output
