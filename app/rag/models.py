"""SQLAlchemy ORM models for RAG product and document metadata."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, Text, func
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Product(Base):
    """Structured product metadata used for SQL narrowing before vector search."""

    __tablename__ = "products"
    __table_args__ = (
        Index("idx_products_tenant_category_brand", "tenant_id", "category", "brand"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    tenant_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    brand: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Structured capacity/power range, parsed from the free-text capacity_range
    # spec (app.rag.capacity) so a real numeric range query is possible — see
    # ProductRepository.find_by_filters. Both bounds share one unit ("KVA"/"A");
    # products with no parseable capacity (e.g. batteries, rated in Ah) leave
    # all three columns null and are simply excluded from capacity matching.
    capacity_min: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    capacity_max: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    capacity_unit: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Unit-specific typed columns (migration 0014) — added alongside, not instead
    # of, capacity_min/max/unit above. That generic pair conflates kVA/A behind
    # one "unit" string, which can't safely support gte/lte/between operators
    # across categories with genuinely different units (a battery's 200 Ah and
    # a UPS's 6 kVA must never be compared against the same requirement). Each
    # column here is populated only for the category it actually applies to —
    # e.g. capacity_kva is UPS/AVR only, capacity_ah/energy_kwh are battery
    # only — and left null everywhere else, the same sparse-column pattern
    # capacity_min/max/unit already established.
    capacity_kva: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    rated_power_kw: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    power_factor: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    current_a: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    # Split from one display string ("3-in / 1-out") into two comparable ints
    # so "three-phase input with single-phase output" is a real `eq` filter on
    # each side independently, not a substring match against a formatted label.
    phase_input_count: Mapped[int | None] = mapped_column(nullable=True)
    phase_output_count: Mapped[int | None] = mapped_column(nullable=True)
    voltage_class_v: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    nominal_voltage_vdc: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    capacity_ah: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    energy_kwh: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    max_discharge_power_kw: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    max_parallel_units: Mapped[int | None] = mapped_column(nullable=True)
    service_life_years: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class ProductSpec(Base):
    """Searchable product spec key/value metadata."""

    __tablename__ = "product_specs"
    __table_args__ = (Index("idx_product_specs_lookup", "tenant_id", "spec_key", "spec_value"),)

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    product_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False, index=True)
    spec_key: Mapped[str] = mapped_column(Text, nullable=False)
    spec_value: Mapped[str] = mapped_column(Text, nullable=False)


class Document(Base):
    """Document metadata; document text chunks live in Qdrant payloads."""

    __tablename__ = "documents"
    __table_args__ = (Index("idx_documents_tenant_type", "tenant_id", "document_type"),)

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    tenant_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False, index=True)
    product_id: Mapped[UUID | None] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("products.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source_path: Mapped[str] = mapped_column(Text, nullable=False)
    document_type: Mapped[str] = mapped_column(Text, nullable=False, server_default="technical_doc")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
