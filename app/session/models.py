"""SQLAlchemy ORM models for durable facts and ephemeral conversation state."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, DateTime, Float, Integer, Numeric, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SessionFacts(Base):
    """Durable CRM-like facts scoped to one tenant session."""

    __tablename__ = "session_facts"

    tenant_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    session_id: Mapped[str] = mapped_column(Text, primary_key=True)
    budget: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    company: Mapped[str | None] = mapped_column(Text, nullable=True)
    industry: Mapped[str | None] = mapped_column(Text, nullable=True)
    product_interest: Mapped[str | None] = mapped_column(Text, nullable=True)
    project_size: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    timeline: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_decision_maker: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    contact_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ConversationState(Base):
    """Short-lived chat flow state scoped to one tenant session."""

    __tablename__ = "conversation_state"

    tenant_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), primary_key=True)
    session_id: Mapped[str] = mapped_column(Text, primary_key=True)
    current_intent: Mapped[str | None] = mapped_column(Text, nullable=True)
    intent_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    awaiting_clarification: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
    )
    clarification_candidates: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default="{}",
    )
    clarification_rounds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    current_plan: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    current_plan_step: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    spec_question_detected: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
    )
    contact_info_captured: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
    )
    handoff_target: Mapped[str | None] = mapped_column(Text, nullable=True)
    language_code: Mapped[str] = mapped_column(Text, nullable=False, server_default="en")
    language_override: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
