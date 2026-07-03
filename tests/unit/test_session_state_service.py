"""Unit tests for Module 03 session state service behavior."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest

from app.config import SessionSettings
from app.session.models import ConversationState, SessionFacts
from app.session.schemas import ConversationStateUpdate, FactsUpdate
from app.session.service import SessionStateService


@dataclass
class DummySettings:
    session: SessionSettings


class FakeRedis:
    def __init__(self, *, fail_writes: bool = False) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int | None] = {}
        self.fail_writes = fail_writes

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        if self.fail_writes:
            raise ConnectionError("redis down")
        self.values[key] = value
        self.ttls[key] = ex

    async def delete(self, key: str) -> None:
        self.values.pop(key, None)
        self.ttls.pop(key, None)


class FakeFactsRepository:
    def __init__(self) -> None:
        self.rows: dict[tuple[uuid.UUID, str], SessionFacts] = {}
        self.upserts = 0

    async def get(self, tenant_id: uuid.UUID, session_id: str) -> SessionFacts | None:
        return self.rows.get((tenant_id, session_id))

    async def upsert(
        self,
        tenant_id: uuid.UUID,
        session_id: str,
        patch: FactsUpdate | Mapping[str, Any],
    ) -> SessionFacts:
        self.upserts += 1
        patch_model = patch if isinstance(patch, FactsUpdate) else FactsUpdate(**dict(patch))
        current = self.rows.get((tenant_id, session_id)) or SessionFacts(
            tenant_id=tenant_id,
            session_id=session_id,
        )
        for key, value in patch_model.non_null_patch().items():
            setattr(current, key, value)
        self.rows[(tenant_id, session_id)] = current
        return current


class FakeStateRepository:
    def __init__(self) -> None:
        self.rows: dict[tuple[uuid.UUID, str], ConversationState] = {}
        self.upserts = 0

    async def get(self, tenant_id: uuid.UUID, session_id: str) -> ConversationState | None:
        return self.rows.get((tenant_id, session_id))

    async def upsert(
        self,
        tenant_id: uuid.UUID,
        session_id: str,
        patch: ConversationStateUpdate | Mapping[str, Any],
    ) -> ConversationState:
        self.upserts += 1
        patch_model = (
            patch if isinstance(patch, ConversationStateUpdate) else ConversationStateUpdate(**dict(patch))
        )
        current = self.rows.get((tenant_id, session_id)) or ConversationState(
            tenant_id=tenant_id,
            session_id=session_id,
            awaiting_clarification=False,
            clarification_candidates=[],
            clarification_rounds=0,
            spec_question_detected=False,
            contact_info_captured=False,
        )
        for key, value in patch_model.patch().items():
            setattr(current, key, value)
        self.rows[(tenant_id, session_id)] = current
        return current

    async def increment_clarification_round(self, tenant_id: uuid.UUID, session_id: str) -> int:
        current = self.rows[(tenant_id, session_id)]
        current.clarification_rounds += 1
        return current.clarification_rounds


def _service(*, redis: FakeRedis | None = None) -> tuple[SessionStateService, FakeFactsRepository, FakeStateRepository, FakeRedis]:
    service = SessionStateService(
        db_session=None,  # type: ignore[arg-type]
        redis=redis or FakeRedis(),  # type: ignore[arg-type]
        settings=DummySettings(session=SessionSettings(conversation_state_ttl_seconds=30)),  # type: ignore[arg-type]
    )
    facts_repo = FakeFactsRepository()
    state_repo = FakeStateRepository()
    service.facts_repo = facts_repo  # type: ignore[assignment]
    service.state_repo = state_repo  # type: ignore[assignment]
    return service, facts_repo, state_repo, service.redis  # type: ignore[return-value]


@pytest.mark.asyncio
async def test_update_facts_does_not_touch_conversation_state() -> None:
    service, facts_repo, state_repo, _redis = _service()
    tenant_id = uuid.uuid4()

    facts = await service.update_facts(tenant_id, "s1", FactsUpdate(budget=Decimal("50000")))

    assert facts.budget == Decimal("50000")
    assert facts_repo.upserts == 1
    assert state_repo.upserts == 0


@pytest.mark.asyncio
async def test_reset_conversation_state_preserves_facts() -> None:
    service, _facts_repo, _state_repo, _redis = _service()
    tenant_id = uuid.uuid4()
    await service.update_facts(tenant_id, "s1", FactsUpdate(company="Makkays", budget=Decimal("25")))
    await service.update_conversation_state(
        tenant_id,
        "s1",
        ConversationStateUpdate(
            awaiting_clarification=True,
            clarification_candidates=["quote", "support"],
            current_plan={"steps": ["ask", "quote"]},
            current_plan_step=1,
        ),
    )

    state = await service.reset_conversation_state(tenant_id, "s1")
    facts = await service.get_facts(tenant_id, "s1")

    assert state.awaiting_clarification is False
    assert state.clarification_candidates == []
    assert state.current_plan is None
    assert state.current_plan_step is None
    assert facts.company == "Makkays"
    assert facts.budget == Decimal("25")


@pytest.mark.asyncio
async def test_facts_write_through_on_redis_failure_still_persists_to_sql() -> None:
    redis = FakeRedis(fail_writes=True)
    service, _facts_repo, _state_repo, _redis = _service(redis=redis)
    tenant_id = uuid.uuid4()

    facts = await service.update_facts(tenant_id, "s1", FactsUpdate(company="Acme"))

    assert facts.company == "Acme"
    assert (await service.facts_repo.get(tenant_id, "s1")).company == "Acme"  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_conversation_state_ttl_reapplied_on_write() -> None:
    service, _facts_repo, _state_repo, redis = _service()
    tenant_id = uuid.uuid4()
    key = f"conversation:state:{tenant_id}:s1"

    await service.update_conversation_state(tenant_id, "s1", ConversationStateUpdate(current_intent="quote"))
    await service.update_conversation_state(tenant_id, "s1", ConversationStateUpdate(last_question="Budget?"))

    assert redis.ttls[key] == 30
