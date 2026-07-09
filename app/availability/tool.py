"""ToolExecutor wrapper for availability checks."""

from __future__ import annotations

from datetime import UTC, datetime

from app.availability.dependencies import get_availability_service
from app.availability.exceptions import ERPConnectionError
from app.availability.schemas import AvailabilityBatchResult, AvailabilityResult
from app.db.engine import get_sessionmaker
from app.dependencies import get_settings
from app.logging_config import get_logger
from app.observability import registry as metrics
from app.tools.schemas import ExecutionContext, SessionContext, ToolExecutionResult

logger = get_logger(__name__)


async def check_availability_tool(
    session: SessionContext,
    context: ExecutionContext,
) -> ToolExecutionResult:
    """Module 10 tool entrypoint for product availability."""
    product_ids = context.get_product_ids() or []
    if not product_ids:
        return ToolExecutionResult(
            step="check_availability",
            success=False,
            result_summary="No product was identified to check availability for.",
            error="No retrieved product IDs",
        )

    settings = get_settings()
    sessionmaker = get_sessionmaker()
    try:
        async with sessionmaker() as db_session:
            service = get_availability_service(db_session, settings)
            results = await service.check_batch(product_ids, session.tenant_id)
    except (ERPConnectionError, NotImplementedError) as exc:
        logger.error("availability_provider_failed", extra={"error": str(exc)})
        return ToolExecutionResult(
            step="check_availability",
            success=False,
            result_summary="Availability check is temporarily unavailable.",
            error=str(exc),
        )

    for result in results:
        metrics.metrics_registry.increment_availability_check(result.source, result.in_stock)

    batch = AvailabilityBatchResult(results=results, checked_at=datetime.now(UTC))
    return ToolExecutionResult(
        step="check_availability",
        success=True,
        result_summary=summarize_availability(batch),
    )


def summarize_availability(batch: AvailabilityBatchResult) -> str:
    """Return a deterministic, user-facing availability summary."""
    if not batch.results:
        return "No products were available to check."
    lines = ["Availability check:"]
    for result in batch.results:
        lines.append(_summarize_result(result))
    return "\n".join(lines)


def _summarize_result(result: AvailabilityResult) -> str:
    status = "in stock" if result.in_stock else "out of stock"
    delivery = (
        f" Estimated delivery: {result.estimated_delivery_days} days."
        if result.estimated_delivery_days is not None
        else ""
    )
    note = f" {result.note}." if result.note else ""
    return f"- Product {result.product_id}: {status}, quantity {result.quantity}.{delivery}{note}"
