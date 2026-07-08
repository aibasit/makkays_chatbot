"""Schemas for clarification template lookup and flow results."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ClarificationTemplate(BaseModel):
    """One template lookup table entry."""

    candidate_key: frozenset[str] | None
    name: str


class ClarificationResult(BaseModel):
    """Question returned to the user by the clarification branch."""

    question_text: str
    source: Literal["template", "template+llm_rewrite"] = "template"
    candidates: list[str] = []
    template_name: str
    clarification_rounds: int
