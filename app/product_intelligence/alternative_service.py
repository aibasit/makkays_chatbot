"""Alternative product finder, scoped strictly to the same product category."""

from __future__ import annotations

import asyncio
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.logging_config import get_logger
from app.rag.embeddings import BgeM3Embedder
from app.rag.models import Product
from app.rag.qdrant_client import QdrantWrapper
from app.rag.repository import ProductRepository
from app.rag.schemas import ProductResult

logger = get_logger(__name__)

_SQL_CANDIDATE_LIMIT = 10
_RESULT_LIMIT = 5


class AlternativeService:
    """Finds alternative products within the same category, ranked by vector similarity."""

    def __init__(
        self,
        db_session: AsyncSession,
        settings: Settings,
        *,
        product_repository: ProductRepository | None = None,
        embedder: BgeM3Embedder | None = None,
        qdrant: QdrantWrapper | None = None,
    ) -> None:
        self.db_session = db_session
        self.settings = settings
        self.product_repository = product_repository or ProductRepository(db_session)
        self.embedder = embedder or BgeM3Embedder(settings.embedding.model_name)
        self.qdrant = qdrant or QdrantWrapper(settings)

    async def find(self, product_id: UUID, tenant_id: UUID) -> list[ProductResult]:
        """Return up to 5 same-category alternatives, ranked by vector similarity."""
        primary = (await self.product_repository.get_by_ids(tenant_id, [product_id])).get(product_id)
        if primary is None or not primary.category:
            return []

        candidates = await self._same_category_candidates(product_id, tenant_id, primary.category)
        if not candidates:
            return []

        query_text = " ".join(filter(None, [primary.name, primary.category, primary.description]))
        loop = asyncio.get_running_loop()
        vectors = await loop.run_in_executor(None, self.embedder.embed, [query_text])

        points = self.qdrant.search(
            self.settings.rag.qdrant_collection_products,
            vectors[0],
            {
                "must": [
                    {"key": "tenant_id", "match": {"value": str(tenant_id)}},
                    {"key": "category", "match": {"value": primary.category}},
                ]
            },
            _RESULT_LIMIT + 1,
        )

        candidate_ids = {product.id for product in candidates}
        results: list[ProductResult] = []
        for point in points:
            payload = getattr(point, "payload", None) or {}
            raw_id = payload.get("product_id")
            if not raw_id:
                continue
            candidate_id = raw_id if isinstance(raw_id, UUID) else UUID(str(raw_id))
            if candidate_id == product_id or candidate_id not in candidate_ids:
                continue
            product = next(item for item in candidates if item.id == candidate_id)
            results.append(
                ProductResult(
                    product_id=candidate_id,
                    name=product.name,
                    brand=product.brand,
                    category=product.category,
                    score=float(getattr(point, "score", 0.0) or 0.0),
                )
            )
            if len(results) >= _RESULT_LIMIT:
                break

        logger.info(
            "alternatives_found",
            extra={"product_id": str(product_id), "tenant_id": str(tenant_id), "result_count": len(results)},
        )
        return results

    async def _same_category_candidates(
        self, product_id: UUID, tenant_id: UUID, category: str
    ) -> list[Product]:
        result = await self.db_session.execute(
            select(Product)
            .where(
                Product.tenant_id == tenant_id,
                Product.category == category,
                Product.id != product_id,
            )
            .limit(_SQL_CANDIDATE_LIMIT)
        )
        return list(result.scalars().all())
