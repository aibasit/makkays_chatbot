"""Ollama availability checks for application startup."""

from __future__ import annotations

import httpx

from app.config import Settings


async def verify_ollama_status(settings: Settings) -> tuple[bool, bool]:
    """Return Ollama service availability and configured model presence."""
    try:
        async with httpx.AsyncClient(base_url=settings.ollama.host.rstrip("/"), timeout=2.0) as client:
            response = await client.get("/api/tags")
            response.raise_for_status()
    except Exception:
        return False, False

    models = response.json().get("models", [])
    model_names = {item.get("name") for item in models if isinstance(item, dict)}
    return True, settings.ollama.model in model_names
