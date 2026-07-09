"""SQLAlchemy model for local product availability."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Computed, DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ProductAvailability(Base):
    """Manual/local availability data for a product."""

    __tablename__ = "product_availability"
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", name="uidx_product_availability_tenant_product"),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    tenant_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False, index=True)
    product_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    in_stock: Mapped[bool] = mapped_column(Computed("quantity > 0", persisted=True))
    estimated_delivery_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default="manual")
