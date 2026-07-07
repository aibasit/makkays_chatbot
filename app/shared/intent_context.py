"""Intent classification models shared by Router, Orchestrator, and Planner."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field


class IntentResult(BaseModel):
    """Outcome of intent classification for a single turn."""

    intent: str
    confidence: float = Field(ge=0.0, le=1.0)
    source: Literal["tier1", "tier2"]
    candidates: list[str] = Field(default_factory=list)
    spec_question_detected: bool = False


class ClassifyIntentArguments(BaseModel):
    """Structured output contract for the Tier 2 `classify_intent` tool call."""

    intent: str
    confidence: float
    candidates: list[str] = Field(default_factory=list)


class PromptProvider(Protocol):
    """Narrow structural protocol for the one method Router/FactsExtractor need.

    Module 08's `app.prompts.manager.PromptManager` (and its own, richer
    `PromptProvider` protocol requiring `get` and `get_latest`) satisfies this
    automatically — it's a structural subtype. Kept separate here rather than
    importing Module 08's protocol so Router's test doubles only need to
    implement `get`, not the `get_latest` method Router never calls.
    """

    def get(self, category: str, name: str, version: str) -> str:
        """Return the exact prompt text for a category/name/version."""
        ...
