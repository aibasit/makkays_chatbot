"""Postgres repositories for RAG product and document metadata."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, not_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.rag.capacity import parse_capacity_range
from app.rag.models import Document, Product, ProductSpec
from app.rag.schemas import Constraint, ExtractedFilters

# Constraint `field` names that map to a real typed column on `Product`
# (added in migration 0014) — these support the full operator set (gte/lte/
# between/nearest included) via real numeric/int comparison. Any constraint
# field *not* listed here is treated as a categorical `product_specs.spec_key`
# instead (see `_CATEGORICAL_SPEC_KEYS`), where only eq/not_eq/in make sense.
_CONSTRAINT_COLUMNS: dict[str, InstrumentedAttribute] = {
    "capacity_kva": Product.capacity_kva,
    "rated_power_kw": Product.rated_power_kw,
    "power_factor": Product.power_factor,
    "current_a": Product.current_a,
    "phase_input_count": Product.phase_input_count,
    "phase_output_count": Product.phase_output_count,
    "voltage_class_v": Product.voltage_class_v,
    "nominal_voltage_vdc": Product.nominal_voltage_vdc,
    "capacity_ah": Product.capacity_ah,
    "energy_kwh": Product.energy_kwh,
    "max_discharge_power_kw": Product.max_discharge_power_kw,
    "max_parallel_units": Product.max_parallel_units,
    "service_life_years": Product.service_life_years,
}

# Constraint `field` names that are categorical and live in `product_specs`
# rather than as a typed column — mapped to the actual `spec_key` written at
# ingestion. Matched case-insensitively via EXISTS/NOT EXISTS, same as the
# older flat `spec_filters` dict, but with real eq/not_eq/in operator support.
_CATEGORICAL_SPEC_KEYS: dict[str, str] = {
    # Ingestion (scripts/ingest_ipower_refined_catalog.py) writes both a raw
    # display spec ("technology" -> "Servo (electro-mechanical)") *and* a
    # normalized one ("technology_key" -> "servo") for these three — the
    # constraint's `value` is always the normalized form (what
    # `FilterExtractor`'s regex detectors produce), so the lookup must target
    # the normalized spec key, not the display one they're easy to confuse
    # with.
    "technology_key": "technology_key",
    "form_factor_key": "form_factor_key",
    "chemistry_key": "chemistry_key",
    # These three have only one spec key each at ingestion (no separate raw
    # vs. normalized pair), so the constraint field name *is* the spec key.
    "battery_mode": "battery_mode",
    "series_key": "series",
    "parallel_capable": "parallel_capable",
    # Reserved for a future client-message detector — no `FilterExtractor`
    # regex produces these yet, so the mapping is currently unused but kept
    # consistent with what ingestion writes (the raw display spec, since
    # there's no normalized form for these two yet).
    "sub_category_key": "subcategory",
    "product_type_key": "type",
    "service_life_type": "service_life_type",
}


def _numeric_condition(column: InstrumentedAttribute, constraint: Constraint) -> Any:
    operator = constraint.operator
    if operator == "eq":
        return column == constraint.value
    if operator == "not_eq":
        return column != constraint.value
    if operator == "gte":
        return column >= constraint.value
    if operator == "lte":
        return column <= constraint.value
    if operator == "between":
        return column.between(constraint.value, constraint.value_max)
    if operator == "in":
        return column.in_(constraint.values or [])
    raise ValueError(f"Unsupported operator '{operator}' for numeric field '{constraint.field}'")


def _categorical_condition(tenant_id: UUID, spec_key: str, constraint: Constraint) -> Any:
    operator = constraint.operator
    if operator not in ("eq", "not_eq", "in"):
        # gte/lte/between/nearest have no meaning on a string spec value — a
        # constraint like this should never be built by FilterExtractor, but
        # fail loudly rather than silently matching everything if it is.
        raise ValueError(f"Unsupported operator '{operator}' for categorical field '{constraint.field}'")
    if operator == "eq":
        values = [str(constraint.value).lower()]
    elif operator == "not_eq":
        values = [str(constraint.value).lower()]
    else:  # "in"
        values = [str(v).lower() for v in (constraint.values or [])]
    exists_clause = (
        select(ProductSpec.id)
        .where(
            ProductSpec.tenant_id == tenant_id,
            ProductSpec.product_id == Product.id,
            func.lower(ProductSpec.spec_key) == spec_key.lower(),
            func.lower(ProductSpec.spec_value).in_(values),
        )
        .exists()
    )
    return not_(exists_clause) if operator == "not_eq" else exists_clause


def _constraint_condition(tenant_id: UUID, constraint: Constraint) -> Any:
    """Return the WHERE condition for one non-`nearest` constraint."""
    column = _CONSTRAINT_COLUMNS.get(constraint.field)
    if column is not None:
        return _numeric_condition(column, constraint)
    spec_key = _CATEGORICAL_SPEC_KEYS.get(constraint.field, constraint.field)
    return _categorical_condition(tenant_id, spec_key, constraint)


# A `nearest` constraint with no other narrowing hard filter could otherwise
# match an entire category — capping the SQL-ranked candidate set here is
# what makes "nearest" actually mean something once handed to Qdrant, which
# only ever re-ranks *within* the candidate ID list, with no notion of
# numeric closeness itself.
_NEAREST_CANDIDATE_LIMIT = 10


def _apply_nearest_ordering(
    stmt: Any, nearest: list[Constraint], *, order_column: Any = None, cap_candidates: bool = False
) -> Any:
    """Apply `ORDER BY ABS(column - value)` for any `nearest` constraints.

    `nearest` only makes sense on a real numeric column — a categorical
    "nearest" constraint (which should never be built, but is defensively
    ignored rather than raised) is skipped. With no `nearest` constraint,
    falls back to `order_column` (e.g. `Product.name` for a stable listing
    order) when one is given.
    """
    numeric_nearest = [c for c in nearest if c.field in _CONSTRAINT_COLUMNS]
    if not numeric_nearest:
        return stmt.order_by(order_column) if order_column is not None else stmt
    for constraint in numeric_nearest:
        column = _CONSTRAINT_COLUMNS[constraint.field]
        stmt = stmt.order_by(func.abs(column - constraint.value))
    if cap_candidates:
        stmt = stmt.limit(_NEAREST_CANDIDATE_LIMIT)
    return stmt


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

    async def get_distinct_model_codes(self, tenant_id: UUID) -> frozenset[str]:
        """Return every ingested `model_code` spec value for one tenant.

        A separate method (not folded into `get_distinct_values`) so existing
        callers/fakes that only expect (brands, categories) are unaffected.
        """
        rows = await self.session.execute(
            select(ProductSpec.spec_value).where(
                ProductSpec.tenant_id == tenant_id,
                ProductSpec.spec_key == "model_code",
            )
        )
        return frozenset(str(row[0]) for row in rows.all() if row[0])

    async def get_distinct_spec_value_map(
        self, tenant_id: UUID, spec_keys: frozenset[str]
    ) -> dict[str, frozenset[str]]:
        """Return `{spec_key: {distinct values}}` for a set of spec keys, in one query.

        A generic counterpart to `get_distinct_model_codes` — used for the
        categorical constraint fields (series, form_factor_key, technology_key,
        ...) so `FilterExtractor` can match against the live vocabulary instead
        of a hardcoded list, the same pattern already used for brand/category/
        model_code. Batched into one round trip (grouped in Python, not SQL)
        rather than one query per field, since a single extract() call may
        need several of these at once.
        """
        if not spec_keys:
            return {}
        lowered_keys = {key.lower() for key in spec_keys}
        rows = await self.session.execute(
            select(ProductSpec.spec_key, ProductSpec.spec_value).where(
                ProductSpec.tenant_id == tenant_id,
                func.lower(ProductSpec.spec_key).in_(lowered_keys),
            )
        )
        grouped: dict[str, set[str]] = {}
        for spec_key, spec_value in rows.all():
            if spec_value:
                grouped.setdefault(str(spec_key).lower(), set()).add(str(spec_value))
        return {key: frozenset(values) for key, values in grouped.items()}

    async def find_by_filters(
        self,
        tenant_id: UUID,
        filters: ExtractedFilters,
    ) -> list[UUID] | None:
        """Return candidate product IDs, or None when no product filters exist."""
        if not filters.has_product_filters():
            return None

        conditions, nearest = self._build_conditions(
            tenant_id,
            brand=filters.brand,
            category=filters.category,
            use_case=filters.use_case,
            capacity_requirement=filters.capacity_requirement,
            capacity_unit=filters.capacity_unit,
            spec_filters=filters.spec_filters,
            constraints=filters.constraints,
        )
        stmt = select(Product.id).where(*conditions)
        stmt = _apply_nearest_ordering(stmt, nearest, cap_candidates=True)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_products(
        self,
        tenant_id: UUID,
        *,
        category: str | None = None,
        brand: str | None = None,
        constraints: list[Constraint] | None = None,
        limit: int,
    ) -> list[Product]:
        """Return every product matching optional category/brand/constraints, up to `limit`.

        Bypasses vector search entirely — for "list all your UPS options"-style
        requests, top-K semantic search would silently truncate a 30+ product
        category down to whatever the default result limit is. Shares
        `_build_conditions` with `find_by_filters` so a request like "list all
        tower UPS" narrows by `form_factor_key` too, rather than the two SQL
        paths silently drifting apart on what "matches" means.
        """
        conditions, nearest = self._build_conditions(
            tenant_id, brand=brand, category=category, constraints=constraints
        )
        stmt = select(Product).where(*conditions)
        stmt = _apply_nearest_ordering(stmt, nearest, order_column=Product.name)
        result = await self.session.execute(stmt.limit(limit))
        return list(result.scalars().all())

    def _build_conditions(
        self,
        tenant_id: UUID,
        *,
        brand: str | None = None,
        category: str | None = None,
        use_case: str | None = None,
        capacity_requirement: Decimal | None = None,
        capacity_unit: str | None = None,
        spec_filters: dict[str, str] | None = None,
        constraints: list[Constraint] | None = None,
    ) -> tuple[list[Any], list[Constraint]]:
        """Build the shared WHERE-clause conditions for both product queries.

        Returns `(conditions, nearest_constraints)` — `nearest` constraints
        aren't boolean conditions (see `Constraint`'s docstring), so they're
        returned separately for the caller to apply as an `ORDER BY`.
        """
        conditions: list[Any] = [Product.tenant_id == tenant_id]
        if brand:
            conditions.append(func.lower(Product.brand) == brand.lower())
        if category:
            conditions.append(func.lower(Product.category) == category.lower())
        if use_case:
            conditions.append(func.lower(func.coalesce(Product.description, "")).like(f"%{use_case.lower()}%"))

        if capacity_requirement is not None:
            conditions.append(Product.capacity_min.is_not(None))
            conditions.append(Product.capacity_max.is_not(None))
            conditions.append(Product.capacity_min <= capacity_requirement)
            conditions.append(Product.capacity_max >= capacity_requirement)
            if capacity_unit:
                conditions.append(func.upper(Product.capacity_unit) == capacity_unit.upper())

        for key, value in (spec_filters or {}).items():
            conditions.append(
                select(ProductSpec.id)
                .where(
                    ProductSpec.tenant_id == tenant_id,
                    ProductSpec.product_id == Product.id,
                    func.lower(ProductSpec.spec_key) == key.lower(),
                    func.lower(ProductSpec.spec_value) == str(value).lower(),
                )
                .exists()
            )

        nearest: list[Constraint] = []
        for constraint in constraints or []:
            if constraint.operator == "nearest":
                nearest.append(constraint)
                continue
            condition = _constraint_condition(tenant_id, constraint)
            if condition is not None:
                conditions.append(condition)
        return conditions, nearest

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
        capacity_kva: Decimal | None = None,
        rated_power_kw: Decimal | None = None,
        power_factor: Decimal | None = None,
        current_a: Decimal | None = None,
        phase_input_count: int | None = None,
        phase_output_count: int | None = None,
        voltage_class_v: Decimal | None = None,
        nominal_voltage_vdc: Decimal | None = None,
        capacity_ah: Decimal | None = None,
        energy_kwh: Decimal | None = None,
        max_discharge_power_kw: Decimal | None = None,
        max_parallel_units: int | None = None,
        service_life_years: Decimal | None = None,
    ) -> Product:
        """Create one product and its specs for local ingestion.

        Structured capacity (capacity_min/max/unit) is auto-derived from a
        "capacity_range" spec entry, if one is present and parseable — callers
        never need to compute it themselves. The unit-specific typed columns
        (capacity_kva, power_factor, ...) are *not* auto-derived the same
        way — a source-specific ingestion script (which already knows which
        unit a raw number means) passes them explicitly.
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
            capacity_kva=capacity_kva,
            rated_power_kw=rated_power_kw,
            power_factor=power_factor,
            current_a=current_a,
            phase_input_count=phase_input_count,
            phase_output_count=phase_output_count,
            voltage_class_v=voltage_class_v,
            nominal_voltage_vdc=nominal_voltage_vdc,
            capacity_ah=capacity_ah,
            energy_kwh=energy_kwh,
            max_discharge_power_kw=max_discharge_power_kw,
            max_parallel_units=max_parallel_units,
            service_life_years=service_life_years,
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
