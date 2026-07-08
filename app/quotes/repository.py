"""Repositories for product pricing and quote persistence."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.quotes.models import ProductPricing, Quote
from app.quotes.schemas import QuoteLineItem


class ProductPricingRepository:
    """SQL access for deterministic product prices."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_prices(
        self,
        tenant_id: UUID,
        product_ids: list[UUID],
    ) -> dict[UUID, ProductPricing]:
        """Return pricing rows keyed by product ID."""
        if not product_ids:
            return {}
        result = await self.session.execute(
            select(ProductPricing).where(
                ProductPricing.tenant_id == tenant_id,
                ProductPricing.product_id.in_(product_ids),
            )
        )
        rows = result.scalars().all()
        return {row.product_id: row for row in rows}

    async def upsert_price(
        self,
        *,
        tenant_id: UUID,
        product_id: UUID,
        unit_price: Decimal,
        currency: str = "USD",
    ) -> ProductPricing:
        """Create or update a product price for local seeding."""
        existing = (
            await self.session.execute(
                select(ProductPricing).where(
                    ProductPricing.tenant_id == tenant_id,
                    ProductPricing.product_id == product_id,
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            existing.unit_price = unit_price
            existing.currency = currency
            await self.session.flush()
            return existing
        row = ProductPricing(
            tenant_id=tenant_id,
            product_id=product_id,
            unit_price=unit_price,
            currency=currency,
        )
        self.session.add(row)
        await self.session.flush()
        return row


class QuoteRepository:
    """SQL access for persisted quotes."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        tenant_id: UUID,
        session_id: str,
        company: str,
        line_items: list[QuoteLineItem],
        total: Decimal,
        currency: str,
    ) -> Quote:
        """Persist one completed quote calculation."""
        row = Quote(
            tenant_id=tenant_id,
            session_id=session_id,
            company=company,
            line_items=[item.model_dump(mode="json") for item in line_items],
            total=total,
            currency=currency,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def get(self, tenant_id: UUID, quote_id: UUID) -> Quote | None:
        """Return a quote by tenant and ID."""
        result = await self.session.execute(
            select(Quote).where(Quote.tenant_id == tenant_id, Quote.id == quote_id)
        )
        return result.scalar_one_or_none()

    async def save_pdf(self, tenant_id: UUID, quote_id: UUID, pdf_bytes: bytes) -> None:
        """Persist generated PDF bytes for a quote."""
        await self.session.execute(
            update(Quote)
            .where(Quote.tenant_id == tenant_id, Quote.id == quote_id)
            .values(pdf_bytes=pdf_bytes)
        )
