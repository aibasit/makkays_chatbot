"""LLM provider availability checks for application startup."""

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


async def verify_groq_status(settings: Settings) -> tuple[bool, bool]:
    """Return Groq API availability and configured model presence."""
    models = await _fetch_groq_models(settings)
    if models is None:
        return False, False
    return True, _model_exists(models, settings.groq.model)


async def verify_llm_status(settings: Settings) -> tuple[str, bool, bool]:
    """Return the active provider name, its availability, and configured model presence."""
    if settings.llm_provider == "groq":
        available, model_exists = await verify_groq_status(settings)
        return "groq", available, model_exists
    available, model_exists = await verify_ollama_status(settings)
    return "ollama", available, model_exists


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


async def _fetch_groq_models(settings: Settings) -> list[dict[str, Any]] | None:
    """Fetch Groq model metadata, returning None when the Groq API is unreachable."""
    try:
        async with httpx.AsyncClient(
            base_url=settings.groq.base_url.rstrip("/"), timeout=2.0
        ) as client:
            response = await client.get(
                "/models",
                headers={"Authorization": f"Bearer {settings.groq.api_key.get_secret_value()}"},
            )
            response.raise_for_status()
    except Exception:
        return None

    models = response.json().get("data", [])
    return [item for item in models if isinstance(item, dict)]


def _model_exists(models: list[dict[str, Any]], model_name: str) -> bool:
    """Return whether model metadata contains the configured model name."""
    model_names = {item.get("name") or item.get("id") for item in models}
    return model_name in model_names
