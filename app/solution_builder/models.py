"""SQLAlchemy ORM models for the wizard, use-case profiles, and saved solutions.

The persisted-solution table is named `SolutionRecord` here (table `solutions`)
to avoid colliding with the Pydantic `Solution` schema in schemas.py.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Integer, Numeric, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WizardSession(Base):
    """Multi-turn requirement-collection wizard state for one session."""

    __tablename__ = "wizard_sessions"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    current_step: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    collected_requirements: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class UseCaseProfile(Base):
    """Pre-defined requirements profile for a named use case (e.g. "school")."""

    __tablename__ = "use_case_profiles"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)
    use_case: Mapped[str] = mapped_column(Text, nullable=False)
    requirements: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SolutionRecord(Base):
    """Persisted computed solution (BOM line items + total)."""

    __tablename__ = "solutions"

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    tenant_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    use_case: Mapped[str | None] = mapped_column(Text, nullable=True)
    requirements: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    line_items: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    total_estimate: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default="USD")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
