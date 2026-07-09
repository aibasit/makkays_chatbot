"""Accessory recommendation: explicit relations first, vector similarity to fill in."""

from __future__ import annotations

import asyncio
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.logging_config import get_logger
from app.product_intelligence.repository import AccessoryRepository
from app.product_intelligence.schemas import AccessoryResult
from app.rag.embeddings import BgeM3Embedder
from app.rag.qdrant_client import QdrantWrapper
from app.rag.repository import ProductRepository

logger = get_logger(__name__)

_MAX_RESULTS = 5
_MIN_EXPLICIT_BEFORE_SUPPLEMENT = 3
_VECTOR_SUPPLEMENT_LIMIT = 8


class AccessoryService:
    """Recommends up to 5 accessories, ranking explicit relations first."""

    def __init__(
        self,
        db_session: AsyncSession,
        settings: Settings,
        *,
        accessory_repository: AccessoryRepository | None = None,
        product_repository: ProductRepository | None = None,
        embedder: BgeM3Embedder | None = None,
        qdrant: QdrantWrapper | None = None,
    ) -> None:
        self.settings = settings
        self.accessory_repository = accessory_repository or AccessoryRepository(db_session)
        self.product_repository = product_repository or ProductRepository(db_session)
        self.embedder = embedder or BgeM3Embedder(settings.embedding.model_name)
        self.qdrant = qdrant or QdrantWrapper(settings)

    async def recommend(self, product_id: UUID, tenant_id: UUID) -> list[AccessoryResult]:
        """Return up to 5 accessories: explicit relations first, then vector similarity."""
        explicit_rows = await self.accessory_repository.find_accessories(product_id, tenant_id)
        accessory_ids = [row.accessory_product_id for row in explicit_rows]
        products_by_id = await self.product_repository.get_by_ids(tenant_id, accessory_ids)

        results = [
            AccessoryResult(
                product_id=row.accessory_product_id,
                name=products_by_id[row.accessory_product_id].name,
                relation_type=row.relation_type,
                source="explicit",
            )
            for row in explicit_rows
            if row.accessory_product_id in products_by_id
        ]

        if len(results) < _MIN_EXPLICIT_BEFORE_SUPPLEMENT:
            exclude_ids = {product_id, *accessory_ids}
            supplement = await self._vector_supplement(product_id, tenant_id, exclude_ids)
            results.extend(supplement)

        logger.info(
            "accessories_recommended",
            extra={"product_id": str(product_id), "tenant_id": str(tenant_id), "result_count": len(results)},
        )
        return results[:_MAX_RESULTS]

    async def _vector_supplement(
        self,
        product_id: UUID,
        tenant_id: UUID,
        exclude_ids: set[UUID],
    ) -> list[AccessoryResult]:
        primary = (await self.product_repository.get_by_ids(tenant_id, [product_id])).get(product_id)
        if primary is None:
            return []

        query_text = " ".join(filter(None, [primary.name, primary.category, primary.description]))
        loop = asyncio.get_running_loop()
        vectors = await loop.run_in_executor(None, self.embedder.embed, [query_text])

        must: list[dict[str, object]] = [{"key": "tenant_id", "match": {"value": str(tenant_id)}}]
        if primary.category:
            must.append({"key": "category", "match": {"value": primary.category}})
        points = self.qdrant.search(
            self._product_collection(), vectors[0], {"must": must}, _VECTOR_SUPPLEMENT_LIMIT
        )

        supplement: list[AccessoryResult] = []
        for point in points:
            payload = getattr(point, "payload", None) or {}
            raw_id = payload.get("product_id")
            if not raw_id:
                continue
            candidate_id = raw_id if isinstance(raw_id, UUID) else UUID(str(raw_id))
            if candidate_id in exclude_ids:
                continue
            supplement.append(
                AccessoryResult(
                    product_id=candidate_id,
                    name=str(payload.get("name") or candidate_id),
                    relation_type="similar_product",
                    source="vector_similarity",
                )
            )
        return supplement

    def _product_collection(self) -> str:
        return self.settings.rag.qdrant_collection_products
