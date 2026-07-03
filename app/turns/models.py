"""SQLAlchemy ORM model for append-only conversation turns."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Float, Index, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PostgresUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ConversationTurn(Base):
    """Append-only per-turn audit record."""

    __tablename__ = "conversation_turns"
    __table_args__ = (
        Index("idx_conversation_turns_session", "tenant_id", "session_id", "turn_number"),
        UniqueConstraint(
            "tenant_id", "session_id", "turn_number", name="uidx_turns_session_number"
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PostgresUUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    tenant_id: Mapped[UUID] = mapped_column(PostgresUUID(as_uuid=True), nullable=False)
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    turn_number: Mapped[int] = mapped_column(Integer, nullable=False)
    user_message: Mapped[str] = mapped_column(Text, nullable=False)
    assistant_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    intent: Mapped[str | None] = mapped_column(Text, nullable=True)
    intent_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    intent_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    candidate_intents: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        server_default="{}",
    )
    prompt_version: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    tool_calls: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
