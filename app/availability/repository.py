"""Repository for local availability records."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.availability.models import ProductAvailability


class AvailabilityRepository:
    """SQL access for product availability."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, product_id: UUID, tenant_id: UUID) -> ProductAvailability | None:
        """Return availability row for one product."""
        result = await self.session.execute(
            select(ProductAvailability).where(
                ProductAvailability.product_id == product_id,
                ProductAvailability.tenant_id == tenant_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_batch(self, product_ids: Iterable[UUID], tenant_id: UUID) -> list[ProductAvailability]:
        """Return availability rows for product IDs."""
        ids = list(product_ids)
        if not ids:
            return []
        result = await self.session.execute(
            select(ProductAvailability).where(
                ProductAvailability.tenant_id == tenant_id,
                ProductAvailability.product_id.in_(ids),
            )
        )
        return list(result.scalars().all())

    async def upsert(
        self,
        *,
        tenant_id: UUID,
        product_id: UUID,
        quantity: int,
        delivery_days: int | None = None,
        source: str = "manual",
    ) -> ProductAvailability:
        """Create or update local availability data."""
        if quantity < 0:
            raise ValueError("quantity must be >= 0")
        stmt = insert(ProductAvailability).values(
            tenant_id=tenant_id,
            product_id=product_id,
            quantity=quantity,
            estimated_delivery_days=delivery_days,
            source=source,
        )
        stmt = (
            stmt.on_conflict_do_update(
                constraint="uidx_product_availability_tenant_product",
                set_={
                    "quantity": stmt.excluded.quantity,
                    "estimated_delivery_days": stmt.excluded.estimated_delivery_days,
                    "source": stmt.excluded.source,
                    "last_updated": func.now(),
                },
            )
            .returning(ProductAvailability)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()
