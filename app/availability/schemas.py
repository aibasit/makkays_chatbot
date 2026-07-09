"""Schemas for product availability checks."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


AvailabilitySource = Literal["local_db", "mock", "erp"]


class AvailabilityResult(BaseModel):
    """Availability for one product."""

    product_id: UUID
    in_stock: bool
    quantity: int = Field(ge=0)
    estimated_delivery_days: int | None = Field(default=None, ge=0)
    source: AvailabilitySource = "local_db"
    note: str | None = None


class AvailabilityBatchResult(BaseModel):
    """Availability for a group of products checked at one time."""

    results: list[AvailabilityResult]
    checked_at: datetime


class AvailabilityCheckRequest(BaseModel):
    """Direct API request model for availability checks."""

    product_id: UUID
