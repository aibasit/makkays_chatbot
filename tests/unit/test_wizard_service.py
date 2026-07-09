"""Unit tests for Module 19 WizardService."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.session.schemas import ConversationStateSchema, FactsSchema
from app.solution_builder.bom_service import ScaleClassifier
from app.solution_builder.exceptions import WizardAlreadyCompleteError
from app.solution_builder.schemas import CallForPricingResult, ProjectScale, Solution
from app.solution_builder.wizard_service import WizardService
from app.tools.schemas import SessionContext


@dataclass
class FakeWizardRow:
    current_step: int
    collected_requirements: dict[str, Any]
    completed: bool


class FakeWizardRepository:
    def __init__(self) -> None:
        self.store: dict[tuple[uuid.UUID, str], FakeWizardRow] = {}

    async def get_active(self, tenant_id: uuid.UUID, session_id: str) -> FakeWizardRow | None:
        row = self.store.get((tenant_id, session_id))
        if row is None or row.completed:
            return None
        return row

    async def get_latest(self, tenant_id: uuid.UUID, session_id: str) -> FakeWizardRow | None:
        return self.store.get((tenant_id, session_id))

    async def upsert(
        self, tenant_id: uuid.UUID, session_id: str, *, step: int, requirements: dict[str, Any], completed: bool
    ) -> FakeWizardRow:
        row = FakeWizardRow(current_step=step, collected_requirements=dict(requirements), completed=completed)
        self.store[(tenant_id, session_id)] = row
        return row


class FakeBOMService:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def build(self, requirements: Any, tenant_id: uuid.UUID) -> Solution:
        self.calls.append(requirements)
        return Solution(
            solution_id=uuid.uuid4(),
            use_case=requirements.use_case,
            line_items=[],
            total_estimate=Decimal("100.00"),
        )


class FakeCallForPricingService:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def handle(self, requirements: Any, scale: ProjectScale, tenant_id: uuid.UUID, session_id: str) -> Any:
        self.calls.append((requirements, scale))
        return CallForPricingResult(
            reference_id="CFP-TEST",
            scale=scale,
            requirements_summary="test",
            message="Routed to sales.",
            lead_id=uuid.uuid4(),
        )


class FakeSolutionExplainer:
    async def explain(self, solution: Solution, llm_client: Any) -> str:
        return "Narrated solution."


class FakeSolutionRepository:
    async def create(self, tenant_id: uuid.UUID, session_id: str, solution: Solution) -> Solution:
        return solution


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        solution_builder=SimpleNamespace(large_device_threshold=500, enterprise_device_threshold=1000)
    )


def _make_service(
    repo: FakeWizardRepository, bom_service: FakeBOMService, cfp_service: FakeCallForPricingService
) -> WizardService:
    return WizardService(
        db_session=None,  # type: ignore[arg-type]
        settings=_settings(),  # type: ignore[arg-type]
        llm_client=None,  # type: ignore[arg-type]
        repository=repo,  # type: ignore[arg-type]
        scale_classifier=ScaleClassifier(_settings()),  # type: ignore[arg-type]
        bom_service=bom_service,  # type: ignore[arg-type]
        call_for_pricing_service=cfp_service,  # type: ignore[arg-type]
        solution_explainer=FakeSolutionExplainer(),  # type: ignore[arg-type]
        solution_repository=FakeSolutionRepository(),  # type: ignore[arg-type]
    )


def _session(tenant_id: uuid.UUID, message: str) -> SessionContext:
    facts = FactsSchema(tenant_id=tenant_id, session_id="s1")
    state = ConversationStateSchema(tenant_id=tenant_id, session_id="s1")
    return SessionContext(tenant_id=tenant_id, session_id="s1", facts=facts, conversation_state=state, message=message)


@pytest.mark.asyncio
async def test_wizard_advances_step_on_each_turn() -> None:
    tenant_id = uuid.uuid4()
    repo = FakeWizardRepository()
    service = _make_service(repo, FakeBOMService(), FakeCallForPricingService())

    step1 = await service.advance(_session(tenant_id, "help me build a solution"))
    assert step1.step_number == 1
    assert step1.is_complete is False
    assert "use case" in (step1.question_text or "").lower()

    step2 = await service.advance(_session(tenant_id, "networking"))
    assert step2.step_number == 2

    step3 = await service.advance(_session(tenant_id, "50"))
    assert step3.step_number == 4  # step 3 (project_size) is auto-classified, no question
    assert "location" in (step3.question_text or "").lower()

    step4 = await service.advance(_session(tenant_id, "Karachi"))
    assert step4.step_number == 5
    assert "brand" in (step4.question_text or "").lower()


@pytest.mark.asyncio
async def test_wizard_marks_complete_when_all_slots_filled() -> None:
    tenant_id = uuid.uuid4()
    repo = FakeWizardRepository()
    bom_service = FakeBOMService()
    service = _make_service(repo, bom_service, FakeCallForPricingService())

    await service.advance(_session(tenant_id, "start"))
    await service.advance(_session(tenant_id, "networking"))
    await service.advance(_session(tenant_id, "50"))
    await service.advance(_session(tenant_id, "Karachi"))
    final_step = await service.advance(_session(tenant_id, "TP-Link"))

    assert final_step.is_complete is True
    assert final_step.solution is not None
    assert final_step.solution.narration == "Narrated solution."
    assert len(bom_service.calls) == 1
    assert bom_service.calls[0].device_count == 50
    assert bom_service.calls[0].location == "Karachi"
    assert bom_service.calls[0].brand_preference == "TP-Link"


@pytest.mark.asyncio
async def test_wizard_routes_large_device_count_to_call_for_pricing() -> None:
    tenant_id = uuid.uuid4()
    repo = FakeWizardRepository()
    bom_service = FakeBOMService()
    cfp_service = FakeCallForPricingService()
    service = _make_service(repo, bom_service, cfp_service)

    await service.advance(_session(tenant_id, "start"))
    await service.advance(_session(tenant_id, "networking"))
    await service.advance(_session(tenant_id, "5000"))
    await service.advance(_session(tenant_id, "Karachi"))
    final_step = await service.advance(_session(tenant_id, ""))

    assert final_step.is_complete is True
    assert final_step.call_for_pricing is not None
    assert final_step.solution is None
    assert len(bom_service.calls) == 0
    assert len(cfp_service.calls) == 1


@pytest.mark.asyncio
async def test_wizard_raises_when_already_complete() -> None:
    tenant_id = uuid.uuid4()
    repo = FakeWizardRepository()
    repo.store[(tenant_id, "s1")] = FakeWizardRow(current_step=5, collected_requirements={}, completed=True)
    service = _make_service(repo, FakeBOMService(), FakeCallForPricingService())

    with pytest.raises(WizardAlreadyCompleteError):
        await service.advance(_session(tenant_id, "anything"))
