"""ERP availability provider stub."""

from __future__ import annotations

from uuid import UUID

from app.availability.schemas import AvailabilityResult
from app.config import Settings


class ERPAvailabilityService:
    """Placeholder for real ERP integration."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def check(self, product_id: UUID, tenant_id: UUID) -> AvailabilityResult:
        """Raise until a real ERP API contract is implemented."""
        raise NotImplementedError(
            "ERPAvailabilityService is not implemented. "
            "Set AVAILABILITY_PROVIDER=local or implement the ERP client."
        )

    async def check_batch(self, product_ids: list[UUID], tenant_id: UUID) -> list[AvailabilityResult]:
        """Raise until a real ERP API contract is implemented."""
        raise NotImplementedError(
            "ERPAvailabilityService is not implemented. "
            "Set AVAILABILITY_PROVIDER=local or implement the ERP client."
        )
