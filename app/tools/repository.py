"""Repository for the append-only tool audit log."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.tools.models import ToolAuditLogEntry


class ToolAuditLogRepository:
    """Raw Postgres access for tool audit log entries. Append-only, mirrors TurnsRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        tenant_id: UUID,
        session_id: str,
        tool_name: str,
        intent: str | None,
        allowed: bool,
        denial_reason: str | None,
    ) -> None:
        """Insert one audit entry; failures are the caller's responsibility to handle."""
        entry = ToolAuditLogEntry(
            tenant_id=tenant_id,
            session_id=session_id,
            tool_name=tool_name,
            intent=intent,
            allowed=allowed,
            denial_reason=denial_reason,
        )
        self.session.add(entry)
        await self.session.flush()
