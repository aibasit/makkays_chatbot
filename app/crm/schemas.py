"""Pydantic schemas for CRM lead capture and retry processing."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LeadCreate(BaseModel):
    """Input required to persist a lead."""

    tenant_id: UUID
    session_id: str
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    company: str | None = None
    product_interest: str | None = None
    message: str | None = None
    qualification: dict[str, Any] = Field(default_factory=dict)
    facts_snapshot: dict[str, Any] = Field(default_factory=dict)

    @field_validator("contact_phone")
    @classmethod
    def normalize_phone(cls, value: str | None) -> str | None:
        """Drop empty phone strings."""
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("contact_email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        """Normalize simple email strings without requiring optional dependencies."""
        if value is None:
            return None
        stripped = value.strip().lower()
        if not stripped:
            return None
        if "@" not in stripped or "." not in stripped.rsplit("@", 1)[-1]:
            raise ValueError("contact_email must look like an email address")
        return stripped


class LeadRead(BaseModel):
    """Read model for a persisted lead."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    session_id: str
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    company: str | None = None
    product_interest: str | None = None
    message: str | None = None
    status: str
    qualification: dict[str, Any]
    facts_snapshot: dict[str, Any]
    created_at: datetime


class LeadResult(BaseModel):
    """Tool-friendly lead creation result."""

    lead_id: UUID
    retry_queue_id: UUID
    summary: str


class RetryQueueResult(BaseModel):
    """Result of one retry worker pass."""

    processed: bool
    queue_id: UUID | None = None
    status: Literal["idle", "synced", "retry_scheduled", "permanently_failed"] = "idle"
    error: str | None = None
