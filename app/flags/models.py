"""SQLAlchemy ORM model for the optional per-tenant feature flag override table."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Text, func
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FeatureFlag(Base):
    """One tenant's override for one named flag; absence means "use the env default"."""

    __tablename__ = "feature_flags"

    tenant_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    flag_name: Mapped[str] = mapped_column(Text, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
