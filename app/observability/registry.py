"""In-process Prometheus metrics registry."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Histogram, REGISTRY

_CONFIDENCE_BUCKETS = (0.0, 0.3, 0.5, 0.7, 0.9, 1.0)
_LATENCY_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)


class MetricsRegistry:
    """Typed wrapper around prometheus_client collectors."""

    def __init__(self, registry: CollectorRegistry = REGISTRY) -> None:
        self.intent_classification_total = Counter(
            "intent_classification_total",
            "Number of intent classifications by source and intent",
            ("source", "intent"),
            registry=registry,
        )
        self.intent_confidence_histogram = Histogram(
            "intent_confidence_histogram",
            "Intent classification confidence observations",
            buckets=_CONFIDENCE_BUCKETS,
            registry=registry,
        )
        self.rag_hit_total = Counter(
            "rag_hit_total",
            "Number of RAG retrievals by hit status",
            ("hit",),
            registry=registry,
        )
        self.quote_result_total = Counter(
            "quote_result_total",
            "Number of quote generation attempts by result",
            ("success",),
            registry=registry,
        )
        self.crm_sync_result_total = Counter(
            "crm_sync_result_total",
            "Number of CRM sync attempts by result",
            ("success",),
            registry=registry,
        )
        self.lead_created_total = Counter(
            "lead_created_total",
            "Number of CRM leads created",
            registry=registry,
        )
        self.tool_result_total = Counter(
            "tool_result_total",
            "Number of tool executions by tool and result",
            ("tool_name", "success"),
            registry=registry,
        )
        self.chat_latency_seconds = Histogram(
            "chat_latency_seconds",
            "Chat request latency in seconds",
            buckets=_LATENCY_BUCKETS,
            registry=registry,
        )
        self.quote_pdf_generated_total = Counter(
            "chatbot_quote_pdf_generated_total",
            "Number of quote PDFs generated",
            ("success",),
            registry=registry,
        )

        self.comparison_requests_total = Counter(
            "chatbot_comparison_requests_total",
            "Number of product comparisons executed",
            ("success",),
            registry=registry,
        )
        self.compatibility_checks_total = Counter(
            "chatbot_compatibility_checks_total",
            "Number of compatibility checks executed",
            ("source", "is_compatible"),
            registry=registry,
        )
        self.accessory_recommendations_total = Counter(
            "chatbot_accessory_recommendations_total",
            "Number of accessory recommendation tool calls",
            ("success",),
            registry=registry,
        )
        self.solution_builds_total = Counter(
            "chatbot_solution_builds_total",
            "Number of BOM solution builds completed",
            ("trigger",),
            registry=registry,
        )
        self.wizard_sessions_total = Counter(
            "chatbot_wizard_sessions_total",
            "Number of wizard sessions started",
            ("completed",),
            registry=registry,
        )
        self.handoff_requests_total = Counter(
            "chatbot_handoff_requests_total",
            "Number of human handoff requests initiated",
            ("target_team", "status"),
            registry=registry,
        )
        self.language_detection_total = Counter(
            "chatbot_language_detection_total",
            "Number of language detections performed",
            ("detected_language",),
            registry=registry,
        )
        self.translation_requests_total = Counter(
            "chatbot_translation_requests_total",
            "Number of response translations performed",
            ("target_language", "success"),
            registry=registry,
        )
        self.availability_checks_total = Counter(
            "chatbot_availability_checks_total",
            "Number of product availability checks",
            ("source", "in_stock"),
            registry=registry,
        )

    def increment_intent_classification(self, source: str, intent: str) -> None:
        self.intent_classification_total.labels(source=source, intent=intent).inc()

    def record_intent_confidence(self, confidence: float) -> None:
        self.intent_confidence_histogram.observe(max(0.0, min(1.0, confidence)))

    def increment_rag_hit(self, hit: bool) -> None:
        self.rag_hit_total.labels(hit=_bool_label(hit)).inc()

    def increment_quote_result(self, success: bool) -> None:
        self.quote_result_total.labels(success=_bool_label(success)).inc()

    def increment_crm_sync_result(self, success: bool) -> None:
        self.crm_sync_result_total.labels(success=_bool_label(success)).inc()

    def increment_lead_created(self) -> None:
        self.lead_created_total.inc()

    def increment_tool_result(self, tool_name: str, success: bool) -> None:
        self.tool_result_total.labels(tool_name=tool_name, success=_bool_label(success)).inc()

    def observe_chat_latency(self, seconds: float) -> None:
        self.chat_latency_seconds.observe(max(0.0, seconds))

    def increment_quote_pdf_generated(self, success: bool) -> None:
        self.quote_pdf_generated_total.labels(success=_bool_label(success)).inc()

    def increment_comparison_request(self, success: bool) -> None:
        self.comparison_requests_total.labels(success=_bool_label(success)).inc()

    def increment_compatibility_check(self, source: str, is_compatible: bool | None) -> None:
        label = "unknown" if is_compatible is None else _bool_label(is_compatible)
        self.compatibility_checks_total.labels(source=source, is_compatible=label).inc()

    def increment_accessory_recommendation(self, success: bool) -> None:
        self.accessory_recommendations_total.labels(success=_bool_label(success)).inc()

    def increment_solution_build(self, trigger: str) -> None:
        self.solution_builds_total.labels(trigger=trigger).inc()

    def increment_wizard_session(self, completed: bool) -> None:
        self.wizard_sessions_total.labels(completed=_bool_label(completed)).inc()

    def increment_handoff_request(self, target_team: str, status: str) -> None:
        self.handoff_requests_total.labels(target_team=target_team, status=status).inc()

    def increment_language_detection(self, detected_language: str) -> None:
        self.language_detection_total.labels(detected_language=detected_language).inc()

    def increment_translation_request(self, target_language: str, success: bool) -> None:
        self.translation_requests_total.labels(
            target_language=target_language,
            success=_bool_label(success),
        ).inc()

    def increment_availability_check(self, source: str, in_stock: bool) -> None:
        self.availability_checks_total.labels(source=source, in_stock=_bool_label(in_stock)).inc()


def _bool_label(value: bool) -> str:
    return "true" if value else "false"


metrics_registry = MetricsRegistry()
