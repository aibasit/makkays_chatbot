"""Integration tests for the FastAPI application shell."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.dependencies import get_settings
from app.main import create_app
from tests.unit.test_config import _write_env


def test_app_starts_and_health_check_returns_ok(tmp_path: Path, monkeypatch) -> None:
    """The app should boot and serve the liveness endpoint."""
    env_file = _write_env(tmp_path / ".env")
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    get_settings.cache_clear()


def test_unhandled_exception_returns_generic_500(tmp_path: Path, monkeypatch) -> None:
    """Unhandled route exceptions should not expose stack traces."""
    env_file = _write_env(tmp_path / ".env")
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    app = create_app()

    @app.get("/explode")
    async def explode() -> None:
        raise RuntimeError("sensitive stack detail")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/explode")

    body = response.json()
    assert response.status_code == 500
    assert body["code"] == "internal_error"
    assert "sensitive stack detail" not in str(body)
    assert "Traceback" not in response.text
    get_settings.cache_clear()

