"""Versioned, categorized prompt library loader and cache."""

from app.prompts.exceptions import PromptNotFoundError
from app.prompts.manager import (
    PROMPT_CATEGORIES,
    STARTUP_PROMPT_REFERENCES,
    PromptManager,
    PromptProvider,
    prompt_manager,
    register_hooks,
)
from app.prompts.schemas import PromptRef, PromptVersionTag

__all__ = [
    "PROMPT_CATEGORIES",
    "STARTUP_PROMPT_REFERENCES",
    "PromptManager",
    "PromptNotFoundError",
    "PromptProvider",
    "PromptRef",
    "PromptVersionTag",
    "prompt_manager",
    "register_hooks",
]
