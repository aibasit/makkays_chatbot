"""Ollama availability checks for application startup."""

from __future__ import annotations

from typing import Any

import httpx

from app.config import Settings


async def check_ollama_available(settings: Settings) -> bool:
    """Return whether the configured Ollama server is reachable."""
    models = await _fetch_ollama_models(settings)
    return models is not None


async def check_model_exists(settings: Settings) -> bool:
    """Return whether the configured Ollama model exists on the server."""
    models = await _fetch_ollama_models(settings)
    if models is None:
        return False
    return _model_exists(models, settings.ollama.model)


async def verify_ollama_status(settings: Settings) -> tuple[bool, bool]:
    """Return Ollama availability and configured model presence."""
    models = await _fetch_ollama_models(settings)
    if models is None:
        return False, False
    return True, _model_exists(models, settings.ollama.model)


async def _fetch_ollama_models(settings: Settings) -> list[dict[str, Any]] | None:
    """Fetch Ollama model metadata, returning None when Ollama is unreachable."""
    try:
        async with httpx.AsyncClient(
            base_url=settings.ollama.host.rstrip("/"), timeout=2.0
        ) as client:
            response = await client.get("/api/tags")
            response.raise_for_status()
    except Exception:
        return None

    models = response.json().get("models", [])
    return [item for item in models if isinstance(item, dict)]


def _model_exists(models: list[dict[str, Any]], model_name: str) -> bool:
    """Return whether model metadata contains the configured model name."""
    model_names = {item.get("name") for item in models}
    return model_name in model_names
