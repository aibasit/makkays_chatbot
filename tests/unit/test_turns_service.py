"""Unit tests for structured logging and turns service assembly."""

from __future__ import annotations

import json
import logging
import uuid
from io import StringIO
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from app.logging_config import JsonFormatter, SecretRedactionFilter
from app.turns.schemas import ConversationTurnCreate
from app.turns.service import TurnsService


class FakeTurnsRepository:
    """Capture created turn schemas without touching a database."""

    def __init__(self) -> None:
        self.created: list[ConversationTurnCreate] = []

    async def create(self, turn: ConversationTurnCreate) -> Any:
        self.created.append(turn)
        return object()

    async def get_next_turn_number(self, tenant_id: uuid.UUID, session_id: str) -> int:
        return len(self.created) + 1


class FakeSession:
    def __init__(self) -> None:
        self.rollbacks = 0

    async def rollback(self) -> None:
        self.rollbacks += 1
        return None


def test_json_formatter_produces_valid_json() -> None:
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("tests.turns.json")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)

    logger.info(
        "turn_recorded", extra={"tenant_id": "tenant", "session_id": "session", "turn_number": 3}
    )

    payload = json.loads(stream.getvalue())
    assert payload["level"] == "INFO"
    assert payload["logger"] == "tests.turns.json"
    assert payload["message"] == "turn_recorded"
    assert payload["tenant_id"] == "tenant"
    assert payload["turn_number"] == 3


def test_secret_redaction_filter_masks_key_fields() -> None:
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(SecretRedactionFilter())
    logger = logging.getLogger("tests.turns.redaction")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)

    logger.info(
        "configured",
        extra={"api_key": "secret-value", "password": "pw", "tenant_id": "tenant"},
    )

    payload = json.loads(stream.getvalue())
    assert payload["api_key"] == "***REDACTED***"
    assert payload["password"] == "***REDACTED***"
    assert payload["tenant_id"] == "tenant"
    assert "secret-value" not in stream.getvalue()


@pytest.mark.asyncio
async def test_turns_service_builds_correct_create_schema() -> None:
    service = TurnsService(FakeSession())  # type: ignore[arg-type]
    repository = FakeTurnsRepository()
    service.repository = repository  # type: ignore[assignment]
    tenant_id = uuid.uuid4()

    await service.record_turn(
        tenant_id=tenant_id,
        session_id="s1",
        turn_number=None,
        user_message="Need a switch",
        assistant_message="Sure.",
        intent_result={
            "intent": "sales_inquiry",
            "confidence": 0.91,
            "source": "tier1",
            "candidate_intents": ["sales_inquiry", "support"],
        },
        prompt_versions={"system": "base_v1", "intent": "sales_inquiry_v2"},
        tool_calls=[
            {"tool": "retrieve_products", "args": {"q": "switch"}, "result_summary": "2 found"}
        ],
    )

    assert len(repository.created) == 1
    created = repository.created[0]
    assert created.tenant_id == tenant_id
    assert created.session_id == "s1"
    assert created.turn_number == 1
    assert created.user_message == "Need a switch"
    assert created.assistant_message == "Sure."
    assert created.intent == "sales_inquiry"
    assert created.intent_confidence == 0.91
    assert created.intent_source == "tier1"
    assert created.candidate_intents == ["sales_inquiry", "support"]
    assert created.prompt_version == {"system": "base_v1", "intent": "sales_inquiry_v2"}
    assert created.tool_calls == [
        {"tool": "retrieve_products", "args": {"q": "switch"}, "result_summary": "2 found"},
    ]


@pytest.mark.asyncio
async def test_turns_service_retries_supplied_stale_turn_number_on_unique_conflict() -> None:
    class ConflictThenSuccessRepository:
        def __init__(self) -> None:
            self.created: list[ConversationTurnCreate] = []
            self.next_number_calls = 0

        async def get_next_turn_number(self, tenant_id: uuid.UUID, session_id: str) -> int:
            self.next_number_calls += 1
            return 2

        async def create(self, turn: ConversationTurnCreate) -> Any:
            self.created.append(turn)
            if len(self.created) == 1:
                raise IntegrityError("insert", {}, Exception("unique violation"))
            return object()

    fake_session = FakeSession()
    service = TurnsService(fake_session)  # type: ignore[arg-type]
    repository = ConflictThenSuccessRepository()
    service.repository = repository  # type: ignore[assignment]

    await service.record_turn(
        tenant_id=uuid.uuid4(),
        session_id="s1",
        turn_number=1,
        user_message="Race me",
        assistant_message="Handled",
    )

    assert [turn.turn_number for turn in repository.created] == [1, 2]
    assert repository.next_number_calls == 1
    assert fake_session.rollbacks == 1
