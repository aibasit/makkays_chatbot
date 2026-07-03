"""Cache-aside service for facts and conversation state."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.session.exceptions import FactsCheckpointError, StateCheckpointError
from app.session.models import ConversationState, SessionFacts
from app.session.repository import ConversationStateRepository, FactsRepository
from app.session.schemas import ConversationStateSchema, ConversationStateUpdate, FactsSchema, FactsUpdate

logger = logging.getLogger(__name__)


class SessionStateService:
    """Coordinates independent Redis and Postgres storage for sessions."""

    def __init__(self, db_session: AsyncSession, redis: Redis, settings: Settings) -> None:
        self.facts_repo = FactsRepository(db_session)
        self.state_repo = ConversationStateRepository(db_session)
        self.redis = redis
        self.settings = settings

    async def get_facts(self, tenant_id: UUID, session_id: str) -> FactsSchema:
        key = self._facts_key(tenant_id, session_id)
        cached = await self._redis_get(key, "facts")
        if cached is not None:
            return FactsSchema.model_validate_json(cached)

        logger.debug("facts_cache_miss tenant_id=%s session_id=%s", tenant_id, session_id)
        try:
            row = await self.facts_repo.get(tenant_id, session_id)
        except Exception as exc:
            logger.warning("facts_db_read_failed tenant_id=%s session_id=%s error=%s", tenant_id, session_id, exc)
            return self._empty_facts(tenant_id, session_id)

        schema = self._facts_from_row(row, tenant_id, session_id)
        if row is not None:
            await self._redis_set(key, schema.model_dump_json(), label="facts", ttl=None)
        return schema

    async def update_facts(
        self,
        tenant_id: UUID,
        session_id: str,
        patch: FactsUpdate | Mapping[str, Any],
    ) -> FactsSchema:
        patch_model = patch if isinstance(patch, FactsUpdate) else FactsUpdate(**dict(patch))
        fields = list(patch_model.non_null_patch())
        if not fields:
            logger.debug("facts_update_noop tenant_id=%s session_id=%s", tenant_id, session_id)
            return await self.get_facts(tenant_id, session_id)

        try:
            row = await self.facts_repo.upsert(tenant_id, session_id, patch_model)
        except Exception as exc:
            logger.error("facts_checkpoint_failed tenant_id=%s session_id=%s error=%s", tenant_id, session_id, exc)
            raise FactsCheckpointError("Failed to checkpoint facts to Postgres") from exc

        schema = self._facts_from_row(row, tenant_id, session_id)
        logger.debug("facts_checkpoint_write tenant_id=%s session_id=%s fields=%s", tenant_id, session_id, fields)
        await self._redis_set(self._facts_key(tenant_id, session_id), schema.model_dump_json(), label="facts", ttl=None)
        return schema

    async def get_conversation_state(self, tenant_id: UUID, session_id: str) -> ConversationStateSchema:
        key = self._state_key(tenant_id, session_id)
        cached = await self._redis_get(key, "state")
        if cached is not None:
            return ConversationStateSchema.model_validate_json(cached)

        logger.debug("state_cache_miss tenant_id=%s session_id=%s", tenant_id, session_id)
        try:
            row = await self.state_repo.get(tenant_id, session_id)
        except Exception as exc:
            logger.warning("state_db_read_failed tenant_id=%s session_id=%s error=%s", tenant_id, session_id, exc)
            return self._empty_state(tenant_id, session_id)

        schema = self._state_from_row(row, tenant_id, session_id)
        if row is not None:
            await self._redis_set(
                key,
                schema.model_dump_json(),
                label="state",
                ttl=self.settings.session.conversation_state_ttl_seconds,
            )
        return schema

    async def update_conversation_state(
        self,
        tenant_id: UUID,
        session_id: str,
        patch: ConversationStateUpdate | Mapping[str, Any],
    ) -> ConversationStateSchema:
        patch_model = (
            patch if isinstance(patch, ConversationStateUpdate) else ConversationStateUpdate(**dict(patch))
        )
        fields = list(patch_model.patch())
        if not fields:
            logger.debug("state_update_noop tenant_id=%s session_id=%s", tenant_id, session_id)
            return await self.get_conversation_state(tenant_id, session_id)

        try:
            row = await self.state_repo.upsert(tenant_id, session_id, patch_model)
        except Exception as exc:
            logger.error("state_checkpoint_failed tenant_id=%s session_id=%s error=%s", tenant_id, session_id, exc)
            raise StateCheckpointError("Failed to checkpoint conversation state to Postgres") from exc

        schema = self._state_from_row(row, tenant_id, session_id)
        logger.debug("state_checkpoint_write tenant_id=%s session_id=%s fields=%s", tenant_id, session_id, fields)
        await self._redis_set(
            self._state_key(tenant_id, session_id),
            schema.model_dump_json(),
            label="state",
            ttl=self.settings.session.conversation_state_ttl_seconds,
        )
        return schema

    async def update_clarification_state(
        self,
        tenant_id: UUID,
        session_id: str,
        *,
        candidates: list[str] | None = None,
        last_question: str | None = None,
    ) -> ConversationStateSchema:
        patch_data: dict[str, Any] = {"awaiting_clarification": True}
        if candidates is not None:
            patch_data["clarification_candidates"] = candidates
        if last_question is not None:
            patch_data["last_question"] = last_question
        patch = ConversationStateUpdate(**patch_data)
        await self.update_conversation_state(tenant_id, session_id, patch)
        try:
            rounds = await self.state_repo.increment_clarification_round(tenant_id, session_id)
        except Exception as exc:
            logger.error("state_checkpoint_failed tenant_id=%s session_id=%s error=%s", tenant_id, session_id, exc)
            raise StateCheckpointError("Failed to increment clarification rounds") from exc

        state = await self.get_conversation_state(tenant_id, session_id)
        refreshed = state.model_copy(update={"clarification_rounds": rounds})
        await self._redis_set(
            self._state_key(tenant_id, session_id),
            refreshed.model_dump_json(),
            label="state",
            ttl=self.settings.session.conversation_state_ttl_seconds,
        )
        return refreshed

    async def reset_conversation_state(self, tenant_id: UUID, session_id: str) -> ConversationStateSchema:
        return await self.update_conversation_state(
            tenant_id,
            session_id,
            ConversationStateUpdate(
                awaiting_clarification=False,
                clarification_candidates=[],
                current_plan=None,
                current_plan_step=None,
            ),
        )

    @staticmethod
    def _facts_key(tenant_id: UUID, session_id: str) -> str:
        return f"session:facts:{tenant_id}:{session_id}"

    @staticmethod
    def _state_key(tenant_id: UUID, session_id: str) -> str:
        return f"conversation:state:{tenant_id}:{session_id}"

    async def _redis_get(self, key: str, label: str) -> str | None:
        try:
            return await self.redis.get(key)
        except Exception as exc:
            logger.warning("%s_redis_read_failed cache=%s error=%s", label, key, exc)
            return None

    async def _redis_set(self, key: str, value: str, *, label: str, ttl: int | None) -> None:
        try:
            if ttl is None:
                await self.redis.set(key, value)
            else:
                await self.redis.set(key, value, ex=ttl)
        except Exception as exc:
            logger.warning("%s_redis_write_failed cache=%s error=%s", label, key, exc)

    @staticmethod
    def _empty_facts(tenant_id: UUID, session_id: str) -> FactsSchema:
        return FactsSchema(tenant_id=tenant_id, session_id=session_id)

    @staticmethod
    def _empty_state(tenant_id: UUID, session_id: str) -> ConversationStateSchema:
        return ConversationStateSchema(tenant_id=tenant_id, session_id=session_id)

    def _facts_from_row(self, row: SessionFacts | None, tenant_id: UUID, session_id: str) -> FactsSchema:
        if row is None:
            return self._empty_facts(tenant_id, session_id)
        return FactsSchema.model_validate(row)

    def _state_from_row(
        self,
        row: ConversationState | None,
        tenant_id: UUID,
        session_id: str,
    ) -> ConversationStateSchema:
        if row is None:
            return self._empty_state(tenant_id, session_id)
        return ConversationStateSchema.model_validate(row)
