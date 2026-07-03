"""Shared SQLAlchemy declarative base and mixins."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID as PostgresUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class TimestampMixin:
    """Reusable created/updated timestamp columns."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class TenantMixin:
    """Reusable tenant ownership column with no database-level default."""

    tenant_id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        nullable=False,
        index=True,
    )
