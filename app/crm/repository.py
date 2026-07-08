"""Repositories for CRM leads and retry queue rows."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crm.models import Lead, RetryQueueItem
from app.crm.schemas import LeadCreate


class LeadRepository:
    """SQL access for captured leads."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, lead: LeadCreate) -> Lead:
        """Persist one lead row."""
        data = lead.model_dump(mode="json")
        data["tenant_id"] = lead.tenant_id
        row = Lead(**data)
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def get(self, tenant_id: UUID, lead_id: UUID) -> Lead | None:
        """Return a tenant-scoped lead."""
        result = await self.session.execute(
            select(Lead).where(Lead.tenant_id == tenant_id, Lead.id == lead_id)
        )
        return result.scalar_one_or_none()


class RetryQueueRepository:
    """SQL access for outbox-style CRM retry rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def enqueue(self, *, tenant_id: UUID, lead_id: UUID, payload: dict[str, Any]) -> RetryQueueItem:
        """Create a pending retry queue item for a new lead."""
        row = RetryQueueItem(tenant_id=tenant_id, lead_id=lead_id, payload=payload)
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def get_due_item(self) -> RetryQueueItem | None:
        """Lock and return one due pending queue item."""
        result = await self.session.execute(
            select(RetryQueueItem)
            .where(
                RetryQueueItem.status == "pending",
                RetryQueueItem.next_retry_at <= datetime.now(timezone.utc),
            )
            .order_by(RetryQueueItem.next_retry_at.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def mark_succeeded(self, item: RetryQueueItem) -> None:
        """Mark a queue item as synced."""
        item.status = "synced"
        item.last_error = None
        await self.session.flush()

    async def mark_failed(
        self,
        item: RetryQueueItem,
        *,
        error: str,
        max_attempts: int,
    ) -> str:
        """Record a failed attempt and either reschedule or permanently fail."""
        item.attempts += 1
        item.last_error = error[:2000]
        if item.attempts >= max_attempts:
            item.status = "permanently_failed"
            await self.session.flush()
            return "permanently_failed"

        delay_minutes = 2 ** max(0, item.attempts - 1)
        item.next_retry_at = datetime.now(timezone.utc) + timedelta(minutes=delay_minutes)
        item.status = "pending"
        await self.session.flush()
        return "retry_scheduled"
