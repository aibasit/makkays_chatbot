"""Repository for the optional `feature_flags` override table."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.flags.models import FeatureFlag


class FeatureFlagsRepository:
    """Raw Postgres access for per-tenant feature flag overrides."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_all(self, tenant_id: UUID) -> dict[str, bool]:
        """Return all flag overrides for one tenant; empty dict means pure env defaults."""
        result = await self.session.execute(
            select(FeatureFlag.flag_name, FeatureFlag.enabled).where(FeatureFlag.tenant_id == tenant_id)
        )
        return dict(result.all())
