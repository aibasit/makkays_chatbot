"""Structured product comparison with LLM narration-only summary."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.schemas import ChatMessage, LLMClientProtocol
from app.logging_config import get_logger
from app.product_intelligence.exceptions import InsufficientProductsForComparisonError
from app.product_intelligence.repository import ProductSpecRepository
from app.product_intelligence.schemas import ComparisonResult
from app.rag.repository import ProductRepository
from app.rag.schemas import ProductResult

logger = get_logger(__name__)

_SUMMARY_SYSTEM_PROMPT = (
    "You compare networking/power products for a sales engineer. Given a structured "
    "comparison table of spec values per product, write a 2-3 sentence recommendation "
    "summary. Only describe the data given; never invent a spec value that is not in "
    "the table."
)


class ComparisonService:
    """Builds a structured spec comparison table plus an LLM narration-only summary."""

    def __init__(
        self,
        db_session: AsyncSession,
        *,
        product_repository: ProductRepository | None = None,
        spec_repository: ProductSpecRepository | None = None,
    ) -> None:
        self.product_repository = product_repository or ProductRepository(db_session)
        self.spec_repository = spec_repository or ProductSpecRepository(db_session)

    async def compare(
        self,
        product_ids: list[UUID],
        tenant_id: UUID,
        llm_client: LLMClientProtocol,
    ) -> ComparisonResult:
        """Build the comparison table from stored specs, then narrate it via the LLM."""
        if len(product_ids) < 2:
            raise InsufficientProductsForComparisonError(
                f"compare() requires at least 2 product_ids, got {len(product_ids)}"
            )

        products_by_id = await self.product_repository.get_by_ids(tenant_id, product_ids)
        products = [
            ProductResult(
                product_id=product_id,
                name=products_by_id[product_id].name,
                brand=products_by_id[product_id].brand,
                category=products_by_id[product_id].category,
                score=1.0,
            )
            for product_id in product_ids
            if product_id in products_by_id
        ]

        specs_by_product = await self.spec_repository.get_specs_for_products(product_ids, tenant_id)
        comparison_table = _build_comparison_table(product_ids, specs_by_product)

        ai_summary = await self._summarize(products, comparison_table, llm_client)
        return ComparisonResult(products=products, comparison_table=comparison_table, ai_summary=ai_summary)

    async def _summarize(
        self,
        products: list[ProductResult],
        comparison_table: dict[str, dict[str, str | None]],
        llm_client: LLMClientProtocol,
    ) -> str:
        table_text = json.dumps(
            {
                "products": [{"id": str(p.product_id), "name": p.name} for p in products],
                "specs": comparison_table,
            },
            separators=(",", ":"),
        )
        messages = [
            ChatMessage(role="system", content=_SUMMARY_SYSTEM_PROMPT),
            ChatMessage(role="user", content=table_text),
        ]
        try:
            response = await llm_client.chat(messages)
            return response.content or ""
        except Exception as exc:
            logger.warning("comparison_summary_llm_failed", extra={"error": str(exc)})
            return ""


def _build_comparison_table(
    product_ids: list[UUID],
    specs_by_product: dict[UUID, list[Any]],
) -> dict[str, dict[str, str | None]]:
    spec_keys: set[str] = set()
    for specs in specs_by_product.values():
        spec_keys.update(spec.spec_key for spec in specs)

    table: dict[str, dict[str, str | None]] = {}
    for spec_key in sorted(spec_keys):
        row: dict[str, str | None] = {}
        for product_id in product_ids:
            value = None
            for spec in specs_by_product.get(product_id, []):
                if spec.spec_key == spec_key:
                    value = spec.spec_value
                    break
            row[str(product_id)] = value
        table[spec_key] = row
    return table
