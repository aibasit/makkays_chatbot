"""Repository for append-only conversation turn persistence."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.turns.models import ConversationTurn
from app.turns.schemas import ConversationTurnCreate


class TurnsRepository:
    """Postgres access for conversation turns."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, turn: ConversationTurnCreate) -> ConversationTurn:
        """Insert one append-only conversation turn."""
        row = ConversationTurn(**turn.model_dump())
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def get_next_turn_number(self, tenant_id: UUID, session_id: str) -> int:
        """Return the next per-session turn number under a transaction-scoped lock."""
        lock_key = f"{tenant_id}:{session_id}"
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": lock_key},
        )
        result = await self.session.execute(
            select(func.coalesce(func.max(ConversationTurn.turn_number), 0) + 1).where(
                ConversationTurn.tenant_id == tenant_id,
                ConversationTurn.session_id == session_id,
            ),
        )
        return int(result.scalar_one())

    async def get_recent_turns(
        self,
        tenant_id: UUID,
        session_id: str,
        limit: int,
    ) -> list[ConversationTurn]:
        """Return recent turns oldest-to-newest, capped by the requested limit."""
        result = await self.session.execute(
            select(ConversationTurn)
            .where(
                ConversationTurn.tenant_id == tenant_id,
                ConversationTurn.session_id == session_id,
            )
            .order_by(desc(ConversationTurn.turn_number))
            .limit(limit)
        )
        return list(reversed(result.scalars().all()))
