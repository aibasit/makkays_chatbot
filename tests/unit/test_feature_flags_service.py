"""Unit tests for Module 09 FeatureFlagsService."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy.exc import ProgrammingError

from app.config import FeatureFlagDefaults
from app.flags.service import FeatureFlagsService


@dataclass
class DummySettings:
    flags: FeatureFlagDefaults = field(default_factory=FeatureFlagDefaults)


class FakeRepository:
    def __init__(self, overrides: dict[str, Any] | None = None, error: Exception | None = None) -> None:
        self.overrides = overrides or {}
        self.error = error
        self.calls = 0

    async def get_all(self, tenant_id: UUID) -> dict[str, Any]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.overrides


def _service(
    overrides: dict[str, Any] | None = None, error: Exception | None = None
) -> tuple[FeatureFlagsService, FakeRepository]:
    service = FeatureFlagsService(db_session=None, settings=DummySettings())  # type: ignore[arg-type]
    repo = FakeRepository(overrides=overrides, error=error)
    service.repository = repo  # type: ignore[assignment]
    return service, repo


@pytest.mark.asyncio
async def test_resolve_uses_env_defaults_when_no_db_rows() -> None:
    service, _repo = _service()

    flags = await service.resolve(uuid.uuid4())

    assert flags.enable_rag is True
    assert flags.enable_quotes is True
    assert flags.enable_image_upload is False


@pytest.mark.asyncio
async def test_resolve_db_override_takes_precedence() -> None:
    service, _repo = _service(overrides={"enable_quotes": False})

    flags = await service.resolve(uuid.uuid4())

    assert flags.enable_quotes is False
    assert flags.enable_rag is True


@pytest.mark.asyncio
async def test_resolve_falls_back_to_env_on_db_error() -> None:
    error = ProgrammingError("SELECT 1", {}, Exception("relation \"feature_flags\" does not exist"))
    service, _repo = _service(error=error)

    flags = await service.resolve(uuid.uuid4())

    assert flags.enable_rag is True
    assert flags.enable_quotes is True


@pytest.mark.asyncio
async def test_resolve_falls_back_to_env_on_unexpected_db_error() -> None:
    service, _repo = _service(error=ConnectionError("db unreachable"))

    flags = await service.resolve(uuid.uuid4())

    assert flags.enable_rag is True


@pytest.mark.asyncio
async def test_unrecognized_flag_name_ignored() -> None:
    service, _repo = _service(overrides={"not_a_real_flag": True, "enable_crm": False})

    flags = await service.resolve(uuid.uuid4())

    assert flags.enable_crm is False
    assert not hasattr(flags, "not_a_real_flag")


@pytest.mark.asyncio
async def test_forced_disabled_flags_always_false_even_with_override() -> None:
    service, _repo = _service(overrides={"enable_voice_chat": True, "enable_image_understanding": True})

    flags = await service.resolve(uuid.uuid4())

    assert flags.enable_voice_chat is False
    assert flags.enable_image_understanding is False


@pytest.mark.asyncio
async def test_invalid_flag_value_is_ignored() -> None:
    service, _repo = _service(overrides={"enable_crm": "not-a-bool"})

    flags = await service.resolve(uuid.uuid4())

    assert flags.enable_crm is True


@pytest.mark.asyncio
async def test_resolve_caches_result_within_ttl() -> None:
    service, repo = _service(overrides={"enable_quotes": False})
    tenant_id = uuid.uuid4()

    first = await service.resolve(tenant_id)
    repo.overrides = {"enable_quotes": True}
    second = await service.resolve(tenant_id)

    assert first is second
    assert second.enable_quotes is False
    assert repo.calls == 1


@pytest.mark.asyncio
async def test_resolve_is_isolated_per_tenant() -> None:
    service, _repo = _service(overrides={"enable_crm": False})

    flags_a = await service.resolve(uuid.uuid4())
    flags_b = await service.resolve(uuid.uuid4())

    assert flags_a.enable_crm is False
    assert flags_b.enable_crm is False
    assert flags_a is not flags_b
