"""Clarification template resolution by candidate intent set."""

from __future__ import annotations

from app.clarification.schemas import ClarificationTemplate

GENERIC_FALLBACK_TEMPLATE = "generic_fallback"

TEMPLATE_REGISTRY: tuple[ClarificationTemplate, ...] = (
    ClarificationTemplate(
        candidate_key=frozenset({"sales_inquiry", "technical_support", "quote_request"}),
        name="sales_vs_support_vs_quote",
    ),
    ClarificationTemplate(
        candidate_key=frozenset({"sales_inquiry", "technical_support"}),
        name="sales_vs_support",
    ),
    ClarificationTemplate(
        candidate_key=frozenset({"sales_inquiry", "quote_request"}),
        name="sales_vs_quote",
    ),
    ClarificationTemplate(
        candidate_key=frozenset({"product_recommendation_wizard"}),
        name="wizard_requirement_collection",
    ),
    ClarificationTemplate(
        candidate_key=frozenset({"product_compatibility"}),
        name="compatibility_type_selection",
    ),
    ClarificationTemplate(
        candidate_key=frozenset({"use_case_recommendation"}),
        name="use_case_selection",
    ),
    ClarificationTemplate(
        candidate_key=frozenset({"human_handoff"}),
        name="handoff_type_selection",
    ),
    ClarificationTemplate(candidate_key=None, name=GENERIC_FALLBACK_TEMPLATE),
)


class TemplateLookup:
    """Resolve a set of candidate intents to a clarification template name."""

    def __init__(self, registry: tuple[ClarificationTemplate, ...] = TEMPLATE_REGISTRY) -> None:
        self._map = {
            item.candidate_key: item.name for item in registry if item.candidate_key is not None
        }
        self._fallback = next(
            (item.name for item in registry if item.candidate_key is None),
            GENERIC_FALLBACK_TEMPLATE,
        )

    def resolve(self, candidates: list[str]) -> str:
        """Return template name for candidates, ignoring candidate order."""
        return self._map.get(frozenset(candidates), self._fallback)
