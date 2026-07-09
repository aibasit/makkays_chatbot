"""Availability service factory."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.availability.erp_client import ERPAvailabilityService
from app.availability.interfaces import AvailabilityService
from app.availability.local_service import LocalAvailabilityService
from app.config import Settings
from app.dependencies import get_settings


def get_availability_service(
    db: AsyncSession,
    settings: Settings | None = None,
) -> AvailabilityService:
    """Return configured availability provider."""
    settings = settings or get_settings()
    provider = settings.availability.provider
    if provider == "local":
        return LocalAvailabilityService(db)
    if provider == "erp":
        return ERPAvailabilityService(settings)
    raise ValueError(f"Unknown AVAILABILITY_PROVIDER: {provider}")
