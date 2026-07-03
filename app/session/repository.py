"""Postgres repositories for durable facts and conversation state."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.session.models import ConversationState, SessionFacts
from app.session.schemas import ConversationStateUpdate, FactsUpdate


class FactsRepository:
    """Raw Postgres access for session facts."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, tenant_id: UUID, session_id: str) -> SessionFacts | None:
        result = await self.session.execute(
            select(SessionFacts).where(
                SessionFacts.tenant_id == tenant_id,
                SessionFacts.session_id == session_id,
            ),
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        tenant_id: UUID,
        session_id: str,
        patch: FactsUpdate | Mapping[str, Any],
    ) -> SessionFacts:
        patch_model = patch if isinstance(patch, FactsUpdate) else FactsUpdate(**dict(patch))
        values = patch_model.non_null_patch()
        if not values:
            existing = await self.get(tenant_id, session_id)
            return existing or SessionFacts(tenant_id=tenant_id, session_id=session_id)

        insert_values = {"tenant_id": tenant_id, "session_id": session_id, **values}
        stmt = insert(SessionFacts).values(**insert_values)
        update_values = {key: stmt.excluded[key] for key in values}
        update_values["updated_at"] = func.now()
        stmt = (
            stmt.on_conflict_do_update(
                index_elements=[SessionFacts.tenant_id, SessionFacts.session_id],
                set_=update_values,
            )
            .returning(SessionFacts)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()


class ConversationStateRepository:
    """Raw Postgres access for conversation state."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, tenant_id: UUID, session_id: str) -> ConversationState | None:
        result = await self.session.execute(
            select(ConversationState).where(
                ConversationState.tenant_id == tenant_id,
                ConversationState.session_id == session_id,
            ),
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        tenant_id: UUID,
        session_id: str,
        patch: ConversationStateUpdate | Mapping[str, Any],
    ) -> ConversationState:
        patch_model = (
            patch if isinstance(patch, ConversationStateUpdate) else ConversationStateUpdate(**dict(patch))
        )
        values = patch_model.patch()
        if not values:
            existing = await self.get(tenant_id, session_id)
            return existing or ConversationState(tenant_id=tenant_id, session_id=session_id)

        insert_values = {"tenant_id": tenant_id, "session_id": session_id, **values}
        stmt = insert(ConversationState).values(**insert_values)
        update_values = {key: stmt.excluded[key] for key in values}
        update_values["updated_at"] = func.now()
        stmt = (
            stmt.on_conflict_do_update(
                index_elements=[ConversationState.tenant_id, ConversationState.session_id],
                set_=update_values,
            )
            .returning(ConversationState)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()

    async def increment_clarification_round(self, tenant_id: UUID, session_id: str) -> int:
        stmt = (
            update(ConversationState)
            .where(
                ConversationState.tenant_id == tenant_id,
                ConversationState.session_id == session_id,
            )
            .values(
                clarification_rounds=ConversationState.clarification_rounds + 1,
                updated_at=func.now(),
            )
            .returning(ConversationState.clarification_rounds)
        )
        result = await self.session.execute(stmt)
        value = result.scalar_one_or_none()
        if value is not None:
            return int(value)

        created = await self.upsert(
            tenant_id,
            session_id,
            ConversationStateUpdate(clarification_rounds=1),
        )
        return int(created.clarification_rounds)
