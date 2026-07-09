"""Pydantic schemas for human handoff workflow."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

VALID_TEAMS: frozenset[str] = frozenset({"sales", "technical", "support"})
HandoffTeam = Literal["sales", "technical", "support"]
HandoffStatus = Literal["pending", "in_progress", "resolved", "cancelled"]


class ExtendedLeadQualification(BaseModel):
    """Additional business context collected during qualification."""

    industry: str | None = None
    project_size: str | None = None
    location: str | None = None
    timeline: str | None = None
    is_decision_maker: bool | None = None


class ConversationExportItem(BaseModel):
    """One exported transcript item."""

    role: Literal["user", "assistant", "system"]
    content: str
    turn_number: int | None = None
    timestamp: datetime | None = None


class HandoffRequest(BaseModel):
    """Data required to create a handoff record."""

    tenant_id: UUID
    session_id: str
    target_team: HandoffTeam
    reference_id: str
    conversation_export: list[dict[str, object]] = Field(default_factory=list)
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None


class HandoffResult(BaseModel):
    """Result consumed by ToolExecutor/respond."""

    handoff_id: UUID
    reference_id: str
    target_team: HandoffTeam
    status: HandoffStatus
    acknowledgement_text: str


class HandoffRead(BaseModel):
    """Read model for a persisted handoff."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    session_id: str
    reference_id: str
    target_team: HandoffTeam
    status: HandoffStatus
    conversation_export: list[dict[str, object]]
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    created_at: datetime
