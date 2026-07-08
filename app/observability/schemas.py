"""Schemas for observability endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ReadyResponse(BaseModel):
    """Readiness response with per-dependency check status."""

    status: Literal["ready", "not_ready"]
    checks: dict[str, bool]
