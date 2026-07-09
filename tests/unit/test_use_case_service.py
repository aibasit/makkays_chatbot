"""Unit tests for Module 19 UseCaseService."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest

from app.solution_builder.exceptions import UseCaseNotFoundError
from app.solution_builder.schemas import Solution
from app.solution_builder.use_case_service import UseCaseService


class FakeProfile:
    def __init__(self, requirements: dict[str, Any]) -> None:
        self.requirements = requirements


class FakeProfileRepository:
    def __init__(self, profile: FakeProfile | None) -> None:
        self.profile = profile
        self.get_calls: list[str] = []

    async def get(self, tenant_id: uuid.UUID, use_case: str) -> FakeProfile | None:
        self.get_calls.append(use_case)
        return self.profile


class FakeBOMService:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def build(self, requirements: Any, tenant_id: uuid.UUID) -> Solution:
        self.calls.append(requirements)
        return Solution(
            solution_id=uuid.uuid4(),
            use_case=requirements.use_case,
            line_items=[],
            total_estimate=Decimal("500.00"),
        )


@pytest.mark.asyncio
async def test_use_case_maps_school_to_requirements() -> None:
    profile = FakeProfile({"device_count": 150})
    repo = FakeProfileRepository(profile)
    bom_service = FakeBOMService()
    service = UseCaseService(
        db_session=None,  # type: ignore[arg-type]
        profile_repository=repo,  # type: ignore[arg-type]
        bom_service=bom_service,  # type: ignore[arg-type]
    )

    result = await service.recommend("school", uuid.uuid4())

    assert repo.get_calls == ["school"]
    assert result.use_case == "school"
    assert result.profile_used is True
    assert bom_service.calls[0].use_case == "school"
    assert bom_service.calls[0].device_count == 150


@pytest.mark.asyncio
async def test_use_case_not_found_raises() -> None:
    repo = FakeProfileRepository(None)
    service = UseCaseService(
        db_session=None,  # type: ignore[arg-type]
        profile_repository=repo,  # type: ignore[arg-type]
        bom_service=FakeBOMService(),  # type: ignore[arg-type]
    )

    with pytest.raises(UseCaseNotFoundError):
        await service.recommend("submarine_base", uuid.uuid4())
