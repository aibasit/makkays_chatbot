"""Unit tests for Module 16 observability endpoints."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.observability import router as observability_router


def test_metrics_endpoint_returns_prometheus_text_format() -> None:
    app = FastAPI()
    app.include_router(observability_router.router)
    client = TestClient(app)

    response = client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "intent_classification_total" in response.text


@pytest.mark.asyncio
async def test_ready_checks_all_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_db() -> bool:
        return True

    async def fake_redis(redis: object) -> bool:
        return True

    async def fake_llm(settings: object) -> bool:
        return True

    monkeypatch.setattr(observability_router, "check_db_ready", fake_db)
    monkeypatch.setattr(observability_router, "check_redis_ready", fake_redis)
    monkeypatch.setattr(observability_router, "check_llm_ready", fake_llm)

    checks = await observability_router.readiness_checks(
        SimpleNamespace(llm_provider="groq"),
        redis=object(),  # type: ignore[arg-type]
    )

    assert checks == {"db": True, "redis": True, "groq": True}


@pytest.mark.parametrize(
    ("db_ok", "redis_ok", "llm_ok"),
    [(False, True, True), (True, False, True), (True, True, False)],
)
@pytest.mark.asyncio
async def test_ready_checks_report_independent_failures(
    monkeypatch: pytest.MonkeyPatch,
    db_ok: bool,
    redis_ok: bool,
    llm_ok: bool,
) -> None:
    async def fake_db() -> bool:
        return db_ok

    async def fake_redis(redis: object) -> bool:
        return redis_ok

    async def fake_llm(settings: object) -> bool:
        return llm_ok

    monkeypatch.setattr(observability_router, "check_db_ready", fake_db)
    monkeypatch.setattr(observability_router, "check_redis_ready", fake_redis)
    monkeypatch.setattr(observability_router, "check_llm_ready", fake_llm)

    checks = await observability_router.readiness_checks(
        SimpleNamespace(llm_provider="ollama"),
        redis=object(),  # type: ignore[arg-type]
    )

    assert checks == {"db": db_ok, "redis": redis_ok, "ollama": llm_ok}
    assert not all(checks.values())
