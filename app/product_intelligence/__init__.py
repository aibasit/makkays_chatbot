"""Product Intelligence Service (Module 18) and Tool Executor registration.

Owns comparison, compatibility, accessory, alternative, spec-explainer, and NL
search capabilities — the layer between raw retrieval (Module 11) and
actionable answers. No business-intelligence logic leaks into Module 11
(retrieval only) or Module 10 (execution only).
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.dependencies import get_settings
from app.db.engine import get_sessionmaker
from app.llm.factory import get_llm_client
from app.logging_config import get_logger
from app.product_intelligence.accessory_service import AccessoryService
from app.product_intelligence.alternative_service import AlternativeService
from app.product_intelligence.comparison_service import ComparisonService
from app.product_intelligence.compatibility_service import CompatibilityService
from app.product_intelligence.exceptions import InsufficientProductsForComparisonError
from app.product_intelligence.nl_search_service import NLSearchService
from app.product_intelligence.repository import AccessoryRepository, CompatibilityRepository, ProductSpecRepository
from app.product_intelligence.schemas import COMPATIBILITY_TYPES, AccessoryResult, ComparisonResult
from app.product_intelligence.specification_service import SpecificationService
from app.rag.schemas import ProductResult
from app.tools.registry import tool_registry
from app.tools.schemas import ExecutionContext, SessionContext, ToolExecutionResult

logger = get_logger(__name__)

__all__ = [
    "AccessoryRepository",
    "AccessoryService",
    "AlternativeService",
    "ComparisonService",
    "CompatibilityRepository",
    "CompatibilityService",
    "NLSearchService",
    "ProductSpecRepository",
    "SpecificationService",
]


async def compare_products_tool(session: SessionContext, context: ExecutionContext) -> ToolExecutionResult:
    """Compare the products surfaced by `retrieve_products` this turn."""
    product_ids = context.get_product_ids() or []
    if len(product_ids) < 2:
        return ToolExecutionResult(
            step="compare_products",
            success=False,
            result_summary="",
            error="Cannot compare: fewer than 2 products found",
        )

    settings = get_settings()
    llm_client = get_llm_client(settings)
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db_session:
        service = ComparisonService(db_session)
        try:
            result = await service.compare(product_ids, session.tenant_id, llm_client)
        except InsufficientProductsForComparisonError as exc:
            return ToolExecutionResult(step="compare_products", success=False, result_summary="", error=str(exc))

    return ToolExecutionResult(
        step="compare_products",
        success=True,
        result_summary=_format_comparison(result),
        product_ids=product_ids,
    )


async def check_compatibility_tool(session: SessionContext, context: ExecutionContext) -> ToolExecutionResult:
    """Check compatibility between the first two products surfaced this turn."""
    product_ids = context.get_product_ids() or []
    if len(product_ids) < 2:
        return ToolExecutionResult(
            step="check_compatibility",
            success=False,
            result_summary="",
            error="Need 2 products to check compatibility",
        )

    compat_type = _infer_compatibility_type(session)
    settings = get_settings()
    llm_client = get_llm_client(settings)
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db_session:
        service = CompatibilityService(db_session)
        result = await service.check(product_ids[0], product_ids[1], compat_type, session.tenant_id, llm_client)

    if result.is_compatible is True:
        verdict = "Compatible"
    elif result.is_compatible is False:
        verdict = "Not compatible"
    else:
        verdict = "Unable to determine compatibility"
    summary = f"{verdict} ({compat_type})."
    if result.notes:
        summary += f" {result.notes}"
    if result.source == "llm_inference":
        summary += " (estimated from specs, not an explicit rule)"
    return ToolExecutionResult(step="check_compatibility", success=True, result_summary=summary)


async def recommend_accessories_tool(session: SessionContext, context: ExecutionContext) -> ToolExecutionResult:
    """Recommend accessories for the first product surfaced this turn."""
    product_ids = context.get_product_ids() or []
    if not product_ids:
        return ToolExecutionResult(
            step="recommend_accessories", success=False, result_summary="", error="No product identified"
        )

    settings = get_settings()
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db_session:
        service = AccessoryService(db_session, settings)
        results = await service.recommend(product_ids[0], session.tenant_id)

    if not results:
        return ToolExecutionResult(step="recommend_accessories", success=True, result_summary="")
    return ToolExecutionResult(step="recommend_accessories", success=True, result_summary=_format_accessories(results))


async def find_alternatives_tool(session: SessionContext, context: ExecutionContext) -> ToolExecutionResult:
    """Find alternatives for the first product surfaced this turn, same category only."""
    product_ids = context.get_product_ids() or []
    if not product_ids:
        return ToolExecutionResult(step="find_alternatives", success=True, result_summary="")

    settings = get_settings()
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db_session:
        service = AlternativeService(db_session, settings)
        results = await service.find(product_ids[0], session.tenant_id)

    if not results:
        return ToolExecutionResult(step="find_alternatives", success=True, result_summary="")
    return ToolExecutionResult(step="find_alternatives", success=True, result_summary=_format_alternatives(results))


async def explain_specification_tool(session: SessionContext, context: ExecutionContext) -> ToolExecutionResult:
    """Explain the spec term implied by this turn's facts, grounded by any retrieved docs."""
    spec_term = session.facts.product_interest or session.conversation_state.last_question or ""
    if not spec_term:
        return ToolExecutionResult(
            step="explain_specification", success=False, result_summary="", error="No term to explain"
        )

    doc_context = _doc_context_from_result(context.retrieve_docs)
    settings = get_settings()
    llm_client = get_llm_client(settings)
    service = SpecificationService()
    explanation = await service.explain(spec_term, doc_context, llm_client)
    return ToolExecutionResult(step="explain_specification", success=True, result_summary=explanation)


# Explicit fixed order for the keyword scan below — COMPATIBILITY_TYPES is a
# frozenset (unordered), and a message can plausibly mention more than one
# keyword (e.g. "is this UPS compatible with the battery?"), so iteration order
# must be deterministic or the resolved compatibility_type would vary by
# Python's set hash ordering rather than by the message content.
_COMPATIBILITY_TYPE_SCAN_ORDER: tuple[str, ...] = ("ups", "battery", "controller", "sfp", "rack")
assert set(_COMPATIBILITY_TYPE_SCAN_ORDER) == COMPATIBILITY_TYPES

_COMPATIBILITY_KEYWORD_PATTERNS: dict[str, re.Pattern[str]] = {
    name: re.compile(rf"\b{name}\b", re.IGNORECASE) for name in _COMPATIBILITY_TYPE_SCAN_ORDER
}


def _infer_compatibility_type(session: SessionContext) -> str:
    """Best-effort keyword scan for a known compatibility_type; 'general' if none match.

    `session.facts` has no dedicated compatibility_type slot, so this scans the
    last thing said in the conversation rather than failing the whole tool call.
    """
    text = " ".join(filter(None, [session.message, session.conversation_state.last_question]))
    for name in _COMPATIBILITY_TYPE_SCAN_ORDER:
        if _COMPATIBILITY_KEYWORD_PATTERNS[name].search(text):
            return name
    return "general"


def _doc_context_from_result(retrieve_docs_result: ToolExecutionResult | None) -> str | None:
    if retrieve_docs_result is None or not retrieve_docs_result.success or not retrieve_docs_result.result_summary:
        return None
    try:
        docs: list[dict[str, Any]] = json.loads(retrieve_docs_result.result_summary)
    except (json.JSONDecodeError, TypeError):
        return None
    chunks = [str(doc.get("chunk_text") or "") for doc in docs if doc.get("chunk_text")]
    return "\n\n".join(chunks) or None


def _format_comparison(result: ComparisonResult) -> str:
    lines = [f"Comparing {', '.join(product.name for product in result.products)}:"]
    for spec_key, values in result.comparison_table.items():
        row = ", ".join(
            f"{next((p.name for p in result.products if str(p.product_id) == pid), pid)}: {value or 'N/A'}"
            for pid, value in values.items()
        )
        lines.append(f"- {spec_key}: {row}")
    if result.ai_summary:
        lines.append("")
        lines.append(result.ai_summary)
    return "\n".join(lines)


def _format_accessories(results: list[AccessoryResult]) -> str:
    items = "\n".join(f"- {item.name} ({item.relation_type})" for item in results)
    return f"Recommended accessories:\n{items}"


def _format_alternatives(results: list[ProductResult]) -> str:
    items = "\n".join(f"- {item.name}" + (f" ({item.brand})" if item.brand else "") for item in results)
    return f"Alternative products in the same category:\n{items}"


tool_registry.register("compare_products", compare_products_tool, flag_name="enable_product_comparison")
tool_registry.register("check_compatibility", check_compatibility_tool, flag_name="enable_compatibility_check")
tool_registry.register(
    "recommend_accessories", recommend_accessories_tool, flag_name="enable_accessory_recommendation"
)
tool_registry.register("find_alternatives", find_alternatives_tool)
tool_registry.register("explain_specification", explain_specification_tool)
