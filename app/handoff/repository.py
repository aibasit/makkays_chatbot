"""Repository for human handoff records."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.handoff.models import HandoffRecord
from app.handoff.schemas import HandoffRequest, HandoffStatus

ACTIVE_HANDOFF_STATUSES = ("pending", "in_progress")


class HandoffRepository:
    """SQL access for handoff requests."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, request: HandoffRequest) -> HandoffRecord:
        """Persist a handoff request."""
        data = request.model_dump(mode="json")
        data["tenant_id"] = request.tenant_id
        row = HandoffRecord(**data)
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def get(self, tenant_id: UUID, handoff_id: UUID) -> HandoffRecord | None:
        """Return a tenant-scoped handoff by ID."""
        result = await self.session.execute(
            select(HandoffRecord).where(
                HandoffRecord.tenant_id == tenant_id,
                HandoffRecord.id == handoff_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_active(self, tenant_id: UUID, session_id: str) -> HandoffRecord | None:
        """Return the active handoff for a session, if one exists."""
        result = await self.session.execute(
            select(HandoffRecord)
            .where(
                HandoffRecord.tenant_id == tenant_id,
                HandoffRecord.session_id == session_id,
                HandoffRecord.status.in_(ACTIVE_HANDOFF_STATUSES),
            )
            .order_by(HandoffRecord.created_at.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_by_session(self, tenant_id: UUID, session_id: str) -> list[HandoffRecord]:
        """List all handoffs for a session."""
        result = await self.session.execute(
            select(HandoffRecord)
            .where(
                HandoffRecord.tenant_id == tenant_id,
                HandoffRecord.session_id == session_id,
            )
            .order_by(HandoffRecord.created_at.asc())
        )
        return list(result.scalars().all())

    async def update_status(
        self,
        tenant_id: UUID,
        handoff_id: UUID,
        status: HandoffStatus,
    ) -> HandoffRecord:
        """Update handoff status and return the row."""
        row = await self.get(tenant_id, handoff_id)
        if row is None:
            raise LookupError(f"Handoff {handoff_id} not found")
        row.status = status
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def count_created_on(self, tenant_id: UUID, day: date) -> int:
        """Return count of handoffs created for tenant on a UTC/local date."""
        result = await self.session.execute(
            select(func.count()).where(
                HandoffRecord.tenant_id == tenant_id,
                func.date(HandoffRecord.created_at) == day,
            )
        )
        return int(result.scalar_one())
