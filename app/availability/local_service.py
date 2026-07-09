"""Local DB-backed availability provider."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.availability.repository import AvailabilityRepository
from app.availability.schemas import AvailabilityResult
from app.logging_config import get_logger

logger = get_logger(__name__)


class LocalAvailabilityService:
    """Local mock provider backed by the product_availability table."""

    def __init__(self, db: AsyncSession, repository: AvailabilityRepository | None = None) -> None:
        self._repo = repository or AvailabilityRepository(db)

    async def check(self, product_id: UUID, tenant_id: UUID) -> AvailabilityResult:
        """Return DB-backed availability or a development mock fallback."""
        row = await self._repo.get(product_id, tenant_id)
        if row is None:
            logger.debug("availability_mock_fallback", extra={"product_id": str(product_id)})
            result = AvailabilityResult(
                product_id=product_id,
                in_stock=True,
                quantity=99,
                estimated_delivery_days=None,
                source="mock",
                note="No availability data - using default mock values",
            )
        else:
            result = AvailabilityResult(
                product_id=row.product_id,
                in_stock=row.quantity > 0,
                quantity=row.quantity,
                estimated_delivery_days=row.estimated_delivery_days,
                source="local_db",
            )
        logger.debug(
            "availability_checked",
            extra={
                "product_id": str(result.product_id),
                "source": result.source,
                "in_stock": result.in_stock,
                "quantity": result.quantity,
            },
        )
        return result

    async def check_batch(self, product_ids: list[UUID], tenant_id: UUID) -> list[AvailabilityResult]:
        """Return availability for product IDs, preserving input order."""
        rows = await self._repo.get_batch(product_ids, tenant_id)
        rows_by_product_id = {row.product_id: row for row in rows}
        results: list[AvailabilityResult] = []
        for product_id in product_ids:
            row = rows_by_product_id.get(product_id)
            if row is None:
                results.append(
                    AvailabilityResult(
                        product_id=product_id,
                        in_stock=True,
                        quantity=99,
                        source="mock",
                        note="No availability data - using default mock values",
                    )
                )
            else:
                results.append(
                    AvailabilityResult(
                        product_id=row.product_id,
                        in_stock=row.quantity > 0,
                        quantity=row.quantity,
                        estimated_delivery_days=row.estimated_delivery_days,
                        source="local_db",
                    )
                )
        return results
