"""Structural interface for availability providers."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.availability.schemas import AvailabilityResult


class AvailabilityService(Protocol):
    """Provider-agnostic availability service contract."""

    async def check(self, product_id: UUID, tenant_id: UUID) -> AvailabilityResult:
        """Return availability for one product."""
        ...

    async def check_batch(self, product_ids: list[UUID], tenant_id: UUID) -> list[AvailabilityResult]:
        """Return availability for each product."""
        ...
