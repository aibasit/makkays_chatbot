"""Plan schemas for the Task Planner."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Plan(BaseModel):
    """Ordered, deterministic execution plan for one classified intent."""

    intent: str
    steps: list[str] = Field(default_factory=list)
