"""Postgres repositories for RAG product and document metadata."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.rag.capacity import parse_capacity_range
from app.rag.models import Document, Product, ProductSpec
from app.rag.schemas import ExtractedFilters


class ProductRepository:
    """SQL access for product metadata and structured narrowing."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_distinct_values(self, tenant_id: UUID) -> tuple[frozenset[str], frozenset[str]]:
        """Return distinct brand and category vocabulary for one tenant."""
        brand_rows = await self.session.execute(
            select(Product.brand)
            .where(Product.tenant_id == tenant_id, Product.brand.is_not(None))
            .distinct()
        )
        category_rows = await self.session.execute(
            select(Product.category)
            .where(Product.tenant_id == tenant_id, Product.category.is_not(None))
            .distinct()
        )
        brands = frozenset(str(row[0]) for row in brand_rows.all() if row[0])
        categories = frozenset(str(row[0]) for row in category_rows.all() if row[0])
        return brands, categories

    async def find_by_filters(
        self,
        tenant_id: UUID,
        filters: ExtractedFilters,
    ) -> list[UUID] | None:
        """Return candidate product IDs, or None when no product filters exist."""
        if not filters.has_product_filters():
            return None

        conditions: list[Any] = [Product.tenant_id == tenant_id]
        if filters.brand:
            conditions.append(func.lower(Product.brand) == filters.brand.lower())
        if filters.category:
            conditions.append(func.lower(Product.category) == filters.category.lower())
        if filters.use_case:
            use_case = f"%{filters.use_case.lower()}%"
            conditions.append(func.lower(func.coalesce(Product.description, "")).like(use_case))

        if filters.capacity_requirement is not None:
            conditions.append(Product.capacity_min.is_not(None))
            conditions.append(Product.capacity_max.is_not(None))
            conditions.append(Product.capacity_min <= filters.capacity_requirement)
            conditions.append(Product.capacity_max >= filters.capacity_requirement)
            if filters.capacity_unit:
                conditions.append(func.upper(Product.capacity_unit) == filters.capacity_unit.upper())

        stmt = select(Product.id).where(*conditions)
        for key, value in filters.spec_filters.items():
            spec_match = (
                select(ProductSpec.id)
                .where(
                    ProductSpec.tenant_id == tenant_id,
                    ProductSpec.product_id == Product.id,
                    func.lower(ProductSpec.spec_key) == key.lower(),
                    func.lower(ProductSpec.spec_value) == str(value).lower(),
                )
                .exists()
            )
            stmt = stmt.where(spec_match)

        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_products(
        self,
        tenant_id: UUID,
        *,
        category: str | None = None,
        brand: str | None = None,
        limit: int,
    ) -> list[Product]:
        """Return every product matching an optional category/brand, up to `limit`.

        Bypasses vector search entirely — for "list all your UPS options"-style
        requests, top-K semantic search would silently truncate a 30+ product
        category down to whatever the default result limit is.
        """
        conditions: list[Any] = [Product.tenant_id == tenant_id]
        if brand:
            conditions.append(func.lower(Product.brand) == brand.lower())
        if category:
            conditions.append(func.lower(Product.category) == category.lower())
        result = await self.session.execute(
            select(Product).where(*conditions).order_by(Product.name).limit(limit)
        )
        return list(result.scalars().all())

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
        for spec in result.scalars().all():
            grouped.setdefault(spec.product_id, []).append(spec)
        return grouped

    async def get_by_ids(self, tenant_id: UUID, product_ids: Iterable[UUID]) -> dict[UUID, Product]:
        """Return products keyed by ID."""
        ids = list(product_ids)
        if not ids:
            return {}
        result = await self.session.execute(
            select(Product).where(Product.tenant_id == tenant_id, Product.id.in_(ids))
        )
        rows = result.scalars().all()
        return {row.id: row for row in rows}

    async def create(
        self,
        *,
        tenant_id: UUID,
        name: str,
        brand: str | None,
        category: str | None,
        description: str | None,
        specs: list[dict[str, Any]],
    ) -> Product:
        """Create one product and its specs for local ingestion.

        Structured capacity (capacity_min/max/unit) is auto-derived from a
        "capacity_range" spec entry, if one is present and parseable — callers
        never need to compute it themselves.
        """
        capacity = None
        for spec in specs:
            key = spec.get("key") or spec.get("spec_key")
            if key and str(key).lower() == "capacity_range":
                value = spec.get("value") or spec.get("spec_value")
                capacity = parse_capacity_range(str(value) if value is not None else None)
                break
        product = Product(
            tenant_id=tenant_id,
            name=name,
            brand=brand,
            category=category,
            description=description,
            capacity_min=capacity.min_value if capacity else None,
            capacity_max=capacity.max_value if capacity else None,
            capacity_unit=capacity.unit if capacity else None,
        )
        self.session.add(product)
        await self.session.flush()
        await self.session.refresh(product)
        for spec in specs:
            key = spec.get("key") or spec.get("spec_key")
            value = spec.get("value") or spec.get("spec_value")
            if key is None or value is None:
                continue
            self.session.add(
                ProductSpec(
                    tenant_id=tenant_id,
                    product_id=product.id,
                    spec_key=str(key),
                    spec_value=str(value),
                )
            )
        await self.session.flush()
        return product


class DocumentRepository:
    """SQL access for document metadata and structured narrowing."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_by_product_ids(
        self,
        tenant_id: UUID,
        product_ids: Iterable[UUID] | None,
    ) -> list[UUID] | None:
        """Return document IDs for products, or None when no product scope exists."""
        if product_ids is None:
            return None
        ids = list(product_ids)
        if not ids:
            return []
        result = await self.session.execute(
            select(Document.id).where(Document.tenant_id == tenant_id, Document.product_id.in_(ids))
        )
        return list(result.scalars().all())

    async def find_by_type(self, tenant_id: UUID, doc_type: str) -> list[UUID]:
        """Return document IDs matching a document type."""
        result = await self.session.execute(
            select(Document.id).where(
                Document.tenant_id == tenant_id,
                func.lower(Document.document_type) == doc_type.lower(),
            )
        )
        return list(result.scalars().all())

    async def get_by_ids(
        self,
        tenant_id: UUID,
        document_ids: Iterable[UUID],
    ) -> dict[UUID, Document]:
        """Return documents keyed by ID."""
        ids = list(document_ids)
        if not ids:
            return {}
        result = await self.session.execute(
            select(Document).where(Document.tenant_id == tenant_id, Document.id.in_(ids))
        )
        rows = result.scalars().all()
        return {row.id: row for row in rows}

    async def create(
        self,
        *,
        tenant_id: UUID,
        title: str,
        source_path: str,
        document_type: str,
        product_id: UUID | None,
    ) -> Document:
        """Create one document metadata row for local ingestion."""
        document = Document(
            tenant_id=tenant_id,
            title=title,
            source_path=source_path,
            document_type=document_type,
            product_id=product_id,
        )
        self.session.add(document)
        await self.session.flush()
        await self.session.refresh(document)
        return document
