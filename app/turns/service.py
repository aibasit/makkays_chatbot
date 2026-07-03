"""Service layer for conversation turn audit logging."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_config import get_logger
from app.turns.repository import TurnsRepository
from app.turns.schemas import ConversationTurnCreate, ConversationTurnRead

logger = get_logger(__name__)


class TurnsService:
    """Assemble and persist append-only conversation turns."""

    def __init__(self, db_session: AsyncSession) -> None:
        self.repository = TurnsRepository(db_session)
        self.db_session = db_session

    async def get_next_turn_number(self, tenant_id: UUID, session_id: str) -> int:
        """Return the next safe per-session turn number."""
        return await self.repository.get_next_turn_number(tenant_id, session_id)

    async def get_recent_turns(
        self,
        tenant_id: UUID,
        session_id: str,
        limit: int = 8,
    ) -> list[ConversationTurnRead]:
        """Return recent turns ordered oldest-to-newest for context assembly."""
        bounded_limit = max(0, min(limit, 8))
        if bounded_limit == 0:
            return []
        rows = await self.repository.get_recent_turns(tenant_id, session_id, bounded_limit)
        return [ConversationTurnRead.model_validate(row) for row in rows]

    async def record_turn(
        self,
        tenant_id: UUID,
        session_id: str,
        turn_number: int | None,
        user_message: str,
        assistant_message: str | None = None,
        intent_result: Mapping[str, Any] | None = None,
        prompt_versions: Mapping[str, Any] | None = None,
        tool_calls: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        """Record one completed turn without allowing logging failure to break chat."""
        normalized_tool_calls = self._validate_tool_calls(tool_calls, tenant_id, session_id)
        for attempt in range(1, 4):
            try:
                resolved_turn_number = (
                    turn_number
                    if turn_number is not None and attempt == 1
                    else await self.get_next_turn_number(tenant_id, session_id)
                )
                turn = self._build_create_schema(
                    tenant_id=tenant_id,
                    session_id=session_id,
                    turn_number=resolved_turn_number,
                    user_message=user_message,
                    assistant_message=assistant_message,
                    intent_result=intent_result,
                    prompt_versions=prompt_versions,
                    tool_calls=normalized_tool_calls,
                )
                await self.repository.create(turn)
                logger.info(
                    "conversation_turn_recorded",
                    extra={
                        "tenant_id": str(tenant_id),
                        "session_id": session_id,
                        "turn_number": resolved_turn_number,
                        "intent": turn.intent,
                    },
                )
                return
            except ValidationError as exc:
                logger.error(
                    "conversation_turn_validation_failed",
                    extra={
                        "tenant_id": str(tenant_id),
                        "session_id": session_id,
                        "error": str(exc),
                    },
                )
                return
            except IntegrityError as exc:
                await self._rollback_safely()
                if attempt < 3:
                    logger.warning(
                        "conversation_turn_number_conflict_retry",
                        extra={
                            "tenant_id": str(tenant_id),
                            "session_id": session_id,
                            "attempt": attempt,
                        },
                    )
                    continue
                self._log_insert_failure(tenant_id, session_id, turn_number, exc)
                return
            except Exception as exc:
                await self._rollback_safely()
                self._log_insert_failure(tenant_id, session_id, turn_number, exc)
                return

    def _build_create_schema(
        self,
        *,
        tenant_id: UUID,
        session_id: str,
        turn_number: int,
        user_message: str,
        assistant_message: str | None,
        intent_result: Mapping[str, Any] | None,
        prompt_versions: Mapping[str, Any] | None,
        tool_calls: list[dict[str, Any]] | None,
    ) -> ConversationTurnCreate:
        intent_data = dict(intent_result or {})
        return ConversationTurnCreate(
            tenant_id=tenant_id,
            session_id=session_id,
            turn_number=turn_number,
            user_message=user_message,
            assistant_message=assistant_message,
            intent=intent_data.get("intent"),
            intent_confidence=intent_data.get("confidence", intent_data.get("intent_confidence")),
            intent_source=intent_data.get("source", intent_data.get("intent_source")),
            candidate_intents=list(intent_data.get("candidate_intents") or []),
            prompt_version=dict(prompt_versions) if prompt_versions is not None else None,
            tool_calls=tool_calls,
        )

    @staticmethod
    def _validate_tool_calls(
        tool_calls: Sequence[Mapping[str, Any]] | None,
        tenant_id: UUID,
        session_id: str,
    ) -> list[dict[str, Any]] | None:
        if tool_calls is None:
            return None
        try:
            normalized = [dict(item) for item in tool_calls]
            ConversationTurnCreate(
                tenant_id=tenant_id,
                session_id=session_id,
                turn_number=1,
                user_message="validation-placeholder",
                tool_calls=normalized,
            )
        except (TypeError, ValueError, ValidationError) as exc:
            logger.error(
                "conversation_turn_tool_calls_invalid",
                extra={"tenant_id": str(tenant_id), "session_id": session_id, "error": str(exc)},
            )
            return None
        return normalized

    async def _rollback_safely(self) -> None:
        try:
            await self.db_session.rollback()
        except Exception as exc:
            logger.error("conversation_turn_rollback_failed", extra={"error": str(exc)})

    @staticmethod
    def _log_insert_failure(
        tenant_id: UUID,
        session_id: str,
        turn_number: int | None,
        exc: Exception,
    ) -> None:
        logger.error(
            "conversation_turn_insert_failed",
            extra={
                "tenant_id": str(tenant_id),
                "session_id": session_id,
                "turn_number": turn_number,
                "error": str(exc),
            },
        )
