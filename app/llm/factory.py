"""Provider selection for the LLM engine."""

from __future__ import annotations

from app.config import Settings
from app.llm.client import OllamaClient
from app.llm.groq_client import GroqClient
from app.llm.schemas import LLMClientProtocol


def get_llm_client(settings: Settings) -> LLMClientProtocol:
    """Return the LLM client for the configured provider."""
    if settings.llm_provider == "groq":
        return GroqClient(settings)
    return OllamaClient(settings)
