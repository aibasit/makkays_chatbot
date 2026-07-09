"""Unit tests for Module 20 human handoff service."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.handoff.exceptions import HandoffAlreadyInitiatedError, InvalidHandoffTeamError
from app.handoff.handoff_service import HandoffService, build_conversation_export, validate_target_team
from app.session.schemas import ConversationStateSchema, FactsSchema
from app.tools.schemas import SessionContext


class FakeHandoffRepository:
    def __init__(self, *, existing: Any | None = None) -> None:
        self.existing = existing
        self.created: Any = None
        self.count = 0

    async def get_active(self, tenant_id: uuid.UUID, session_id: str) -> Any | None:
        return self.existing

    async def count_created_on(self, tenant_id: uuid.UUID, day: object) -> int:
        return self.count

    async def create(self, request: Any) -> Any:
        self.created = request
        return SimpleNamespace(
            id=uuid.uuid4(),
            tenant_id=request.tenant_id,
            session_id=request.session_id,
            reference_id=request.reference_id,
            target_team=request.target_team,
            status="pending",
            conversation_export=request.conversation_export,
            contact_name=request.contact_name,
            contact_email=request.contact_email,
            contact_phone=request.contact_phone,
            created_at=datetime.now(UTC),
        )


class FakeTurnsRepository:
    async def get_recent_turns(self, tenant_id: uuid.UUID, session_id: str, limit: int) -> list[Any]:
        return [
            SimpleNamespace(
                turn_number=1,
                user_message="I need help with switches.",
                assistant_message="Sure, what scale?",
                created_at=datetime.now(UTC),
            )
        ]


class FakeNotificationService:
    async def send_handoff_notification(self, handoff: Any, facts: Any) -> bool:
        return True


def _session(tenant_id: uuid.UUID | None = None) -> SessionContext:
    tenant_id = tenant_id or uuid.uuid4()
    return SessionContext(
        tenant_id=tenant_id,
        session_id="session-1",
        facts=FactsSchema(
            tenant_id=tenant_id,
            session_id="session-1",
            company="Acme",
            product_interest="network switches",
            budget=Decimal("5000"),
            contact_name="Ayesha",
            contact_email="ayesha@example.com",
        ),
        conversation_state=ConversationStateSchema(tenant_id=tenant_id, session_id="session-1"),
        message="connect me to technical support",
    )


@pytest.mark.asyncio
async def test_initiate_handoff_creates_db_record() -> None:
    repo = FakeHandoffRepository()
    service = HandoffService(
        db_session=None,  # type: ignore[arg-type]
        repository=repo,  # type: ignore[arg-type]
        turns_repository=FakeTurnsRepository(),  # type: ignore[arg-type]
        notification_service=FakeNotificationService(),  # type: ignore[arg-type]
    )
    service._notify_later = lambda handoff, session: None  # type: ignore[method-assign]

    result = await service.initiate(_session(), "technical")

    assert result.reference_id.startswith("HO-")
    assert result.target_team == "technical"
    assert result.status == "pending"
    assert "Technical team" in result.acknowledgement_text
    assert repo.created is not None
    assert repo.created.conversation_export[0]["role"] == "user"


@pytest.mark.asyncio
async def test_initiate_handoff_raises_on_duplicate() -> None:
    existing = SimpleNamespace(reference_id="HO-20260708-001")
    service = HandoffService(
        db_session=None,  # type: ignore[arg-type]
        repository=FakeHandoffRepository(existing=existing),  # type: ignore[arg-type]
        turns_repository=FakeTurnsRepository(),  # type: ignore[arg-type]
        notification_service=FakeNotificationService(),  # type: ignore[arg-type]
    )

    with pytest.raises(HandoffAlreadyInitiatedError) as exc_info:
        await service.initiate(_session(), "sales")

    assert exc_info.value.reference_id == "HO-20260708-001"


def test_invalid_team_raises_error() -> None:
    with pytest.raises(InvalidHandoffTeamError):
        validate_target_team("billing")


def test_build_conversation_export_includes_user_and_assistant_messages() -> None:
    turn = SimpleNamespace(
        turn_number=3,
        user_message="hello",
        assistant_message="hi",
        created_at=datetime(2026, 7, 8, tzinfo=UTC),
    )

    export = build_conversation_export([turn])

    assert export == [
        {
            "role": "user",
            "content": "hello",
            "turn_number": 3,
            "timestamp": "2026-07-08T00:00:00+00:00",
        },
        {
            "role": "assistant",
            "content": "hi",
            "turn_number": 3,
            "timestamp": "2026-07-08T00:00:00+00:00",
        },
    ]
