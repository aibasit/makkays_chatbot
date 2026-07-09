"""Human handoff service and Module 10 tool wrapper."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.crm.notifications import NotificationService
from app.dependencies import get_settings
from app.handoff.exceptions import HandoffAlreadyInitiatedError, InvalidHandoffTeamError
from app.handoff.repository import HandoffRepository
from app.handoff.schemas import (
    HandoffRead,
    HandoffRequest,
    HandoffResult,
    HandoffTeam,
    VALID_TEAMS,
)
from app.logging_config import get_logger
from app.observability import registry as metrics
from app.tools.schemas import ExecutionContext, SessionContext, ToolExecutionResult
from app.turns.repository import TurnsRepository

logger = get_logger(__name__)


class HandoffService:
    """Create one active handoff per session and notify the selected team."""

    def __init__(
        self,
        db_session: AsyncSession,
        *,
        repository: HandoffRepository | None = None,
        turns_repository: TurnsRepository | None = None,
        notification_service: NotificationService | None = None,
    ) -> None:
        self.repository = repository or HandoffRepository(db_session)
        self.turns_repository = turns_repository or TurnsRepository(db_session)
        self.notification_service = notification_service or NotificationService(get_settings())

    async def initiate(self, session: SessionContext, target_team: str) -> HandoffResult:
        """Create a handoff request, export recent conversation, and notify the team."""
        team = validate_target_team(target_team)
        existing = await self.repository.get_active(session.tenant_id, session.session_id)
        if existing is not None:
            logger.warning(
                "handoff_duplicate_attempt",
                extra={
                    "tenant_id": str(session.tenant_id),
                    "session_id": session.session_id,
                    "reference_id": existing.reference_id,
                },
            )
            raise HandoffAlreadyInitiatedError(existing.reference_id)

        turns = await self.turns_repository.get_recent_turns(
            session.tenant_id,
            session.session_id,
            limit=50,
        )
        conversation_export = build_conversation_export(turns)
        if len(turns) >= 50:
            conversation_export.insert(
                0,
                {
                    "role": "system",
                    "content": "Conversation export is capped at the most recent 50 turns.",
                    "turn_number": None,
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
        reference_id = await self._next_reference_id(session)
        record = await self.repository.create(
            HandoffRequest(
                tenant_id=session.tenant_id,
                session_id=session.session_id,
                target_team=team,
                reference_id=reference_id,
                conversation_export=conversation_export,
                contact_name=session.facts.contact_name,
                contact_email=session.facts.contact_email,
                contact_phone=session.facts.contact_phone,
            )
        )
        result = HandoffResult(
            handoff_id=record.id,
            reference_id=record.reference_id,
            target_team=cast(HandoffTeam, record.target_team),
            status=cast(Any, record.status),
            acknowledgement_text=acknowledgement_text(cast(HandoffTeam, record.target_team), record.reference_id),
        )
        self._notify_later(HandoffRead.model_validate(record), session)
        metrics.metrics_registry.increment_handoff_request(team, "pending")
        logger.info(
            "handoff_created",
            extra={
                "handoff_id": str(record.id),
                "tenant_id": str(session.tenant_id),
                "session_id": session.session_id,
                "target_team": team,
                "reference_id": record.reference_id,
            },
        )
        return result

    async def _next_reference_id(self, session: SessionContext) -> str:
        today = datetime.now(UTC).date()
        sequence = await self.repository.count_created_on(session.tenant_id, today)
        return f"HO-{today:%Y%m%d}-{sequence + 1:03d}"

    def _notify_later(self, handoff: HandoffRead, session: SessionContext) -> None:
        async def _send() -> None:
            try:
                await self.notification_service.send_handoff_notification(handoff, session.facts)
            except Exception as exc:
                logger.warning(
                    "handoff_notification_failed",
                    extra={"reference_id": handoff.reference_id, "error": str(exc)},
                )

        try:
            asyncio.create_task(_send())
        except RuntimeError:
            logger.debug("handoff_notification_skipped_no_running_loop", extra={"reference_id": handoff.reference_id})


async def initiate_handoff_tool(
    session: SessionContext,
    context: ExecutionContext,
) -> ToolExecutionResult:
    """Module 10 tool entrypoint for human handoff."""
    from app.db.engine import get_sessionmaker

    target_team = infer_target_team(session)
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db_session:
        service = HandoffService(db_session)
        try:
            result = await service.initiate(session, target_team)
            await db_session.commit()
        except HandoffAlreadyInitiatedError as exc:
            await db_session.rollback()
            summary = (
                f"A handoff is already active for this conversation. "
                f"Reference: {exc.reference_id}."
            )
            return ToolExecutionResult(step="initiate_handoff", success=False, result_summary=summary)
        except InvalidHandoffTeamError:
            await db_session.rollback()
            service = HandoffService(db_session)
            result = await service.initiate(session, "sales")
            await db_session.commit()
    return ToolExecutionResult(
        step="initiate_handoff",
        success=True,
        result_summary=result.acknowledgement_text,
    )


def validate_target_team(target_team: str) -> HandoffTeam:
    """Return a valid handoff team or raise."""
    normalized = target_team.strip().lower()
    if normalized not in VALID_TEAMS:
        raise InvalidHandoffTeamError(f"Invalid handoff target team: {target_team}")
    return cast(HandoffTeam, normalized)


def infer_target_team(session: SessionContext) -> HandoffTeam:
    """Resolve target team from state first, then current user text, then sales."""
    state_target = getattr(session.conversation_state, "handoff_target", None)
    if isinstance(state_target, str) and state_target.strip().lower() in VALID_TEAMS:
        return cast(HandoffTeam, state_target.strip().lower())

    message = session.message.lower()
    if "technical" in message or "engineer" in message:
        return "technical"
    if "support" in message or "issue" in message or "problem" in message:
        return "support"
    return "sales"


def build_conversation_export(turns: list[Any]) -> list[dict[str, object]]:
    """Serialize conversation turns into a role/content transcript."""
    export: list[dict[str, object]] = []
    for turn in turns:
        turn_number = getattr(turn, "turn_number", None)
        created_at = getattr(turn, "created_at", None)
        timestamp = created_at.isoformat() if hasattr(created_at, "isoformat") else None
        user_message = getattr(turn, "user_message", None)
        assistant_message = getattr(turn, "assistant_message", None)
        if user_message:
            export.append(
                {
                    "role": "user",
                    "content": user_message,
                    "turn_number": turn_number,
                    "timestamp": timestamp,
                }
            )
        if assistant_message:
            export.append(
                {
                    "role": "assistant",
                    "content": assistant_message,
                    "turn_number": turn_number,
                    "timestamp": timestamp,
                }
            )
    return export


def acknowledgement_text(target_team: HandoffTeam, reference_id: str) -> str:
    """Build deterministic user-facing handoff acknowledgement."""
    label = {"sales": "Sales", "technical": "Technical", "support": "Support"}[target_team]
    return (
        f"I've connected you with our {label} team. Reference: {reference_id}. "
        "Someone will contact you shortly."
    )
