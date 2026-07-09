"""SQLAlchemy ORM models for compatibility rules and accessory relations."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CompatibilityRule(Base):
    """Explicit tenant-defined compatibility rule between two products."""

    __tablename__ = "compatibility_rules"
    __table_args__ = (
        Index(
            "idx_compat_rules_lookup",
            "tenant_id",
            "primary_product_id",
            "compatibility_type",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)
    primary_product_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("products.id"), nullable=False
    )
    secondary_product_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("products.id"), nullable=False
    )
    compatibility_type: Mapped[str] = mapped_column(Text, nullable=False)
    is_compatible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AccessoryRelation(Base):
    """Explicit tenant-defined accessory relation for a primary product."""

    __tablename__ = "accessory_relations"
    __table_args__ = (
        Index("idx_accessory_lookup", "tenant_id", "primary_product_id", "relation_type"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)
    primary_product_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("products.id"), nullable=False
    )
    accessory_product_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), ForeignKey("products.id"), nullable=False
    )
    relation_type: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
