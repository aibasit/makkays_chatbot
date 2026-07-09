"""Postgres repositories for compatibility rules, accessory relations, and product specs."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.product_intelligence.models import AccessoryRelation, CompatibilityRule
from app.rag.models import ProductSpec


class CompatibilityRepository:
    """SQL access for explicit compatibility rules."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find(
        self,
        primary_id: UUID,
        secondary_id: UUID,
        compatibility_type: str,
        tenant_id: UUID,
    ) -> CompatibilityRule | None:
        """Return the explicit rule for this product pair/type, checked in either order."""
        result = await self.session.execute(
            select(CompatibilityRule).where(
                CompatibilityRule.tenant_id == tenant_id,
                CompatibilityRule.compatibility_type == compatibility_type,
                (
                    (CompatibilityRule.primary_product_id == primary_id)
                    & (CompatibilityRule.secondary_product_id == secondary_id)
                )
                | (
                    (CompatibilityRule.primary_product_id == secondary_id)
                    & (CompatibilityRule.secondary_product_id == primary_id)
                ),
            )
        )
        return result.scalars().first()

    async def create(self, tenant_id: UUID, data: dict[str, Any]) -> CompatibilityRule:
        """Create one explicit compatibility rule (local-dev seeding)."""
        rule = CompatibilityRule(tenant_id=tenant_id, **data)
        self.session.add(rule)
        await self.session.flush()
        await self.session.refresh(rule)
        return rule


class AccessoryRepository:
    """SQL access for explicit accessory relations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_accessories(self, product_id: UUID, tenant_id: UUID) -> list[AccessoryRelation]:
        """Return explicit accessory relations for one primary product."""
        result = await self.session.execute(
            select(AccessoryRelation).where(
                AccessoryRelation.tenant_id == tenant_id,
                AccessoryRelation.primary_product_id == product_id,
            )
        )
        return list(result.scalars().all())

    async def create(self, tenant_id: UUID, data: dict[str, Any]) -> AccessoryRelation:
        """Create one explicit accessory relation (local-dev seeding)."""
        relation = AccessoryRelation(tenant_id=tenant_id, **data)
        self.session.add(relation)
        await self.session.flush()
        await self.session.refresh(relation)
        return relation


class ProductSpecRepository:
    """SQL access for product spec rows, grouped per product for comparison tables."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_specs_for_products(
        self,
        product_ids: Iterable[UUID],
        tenant_id: UUID,
    ) -> dict[UUID, list[ProductSpec]]:
        """Return spec rows keyed by product ID; products with no specs are omitted."""
        ids = list(product_ids)
        if not ids:
            return {}
        result = await self.session.execute(
            select(ProductSpec).where(
                ProductSpec.tenant_id == tenant_id,
                ProductSpec.product_id.in_(ids),
            )
        )
        grouped: dict[UUID, list[ProductSpec]] = {}
        for row in result.scalars().all():
            grouped.setdefault(row.product_id, []).append(row)
        return grouped
