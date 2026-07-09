"""Repositories for wizard sessions, use-case profiles, and saved solutions."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.solution_builder.models import SolutionRecord, UseCaseProfile, WizardSession
from app.solution_builder.schemas import BOMLineItem, Solution


class WizardSessionRepository:
    """SQL access for multi-turn wizard state."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_active(self, tenant_id: UUID, session_id: str) -> WizardSession | None:
        """Return the in-progress (not yet completed) wizard session, if any."""
        result = await self.session.execute(
            select(WizardSession).where(
                WizardSession.tenant_id == tenant_id,
                WizardSession.session_id == session_id,
                WizardSession.completed.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def get_latest(self, tenant_id: UUID, session_id: str) -> WizardSession | None:
        """Return the most recent wizard session regardless of completion status.

        Used by `WizardService.advance` to detect "already complete" — `get_active`
        can't do this since it only ever returns non-completed rows by design (the
        partial unique index on `completed = false` is what allows a session to
        run the wizard again later without conflicting with an old completed row).
        """
        result = await self.session.execute(
            select(WizardSession)
            .where(WizardSession.tenant_id == tenant_id, WizardSession.session_id == session_id)
            .order_by(desc(WizardSession.created_at))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        tenant_id: UUID,
        session_id: str,
        *,
        step: int,
        requirements: dict[str, Any],
        completed: bool,
    ) -> WizardSession:
        """Create or advance the active wizard session for this tenant/session."""
        existing = await self.get_active(tenant_id, session_id)
        if existing is not None:
            existing.current_step = step
            existing.collected_requirements = requirements
            existing.completed = completed
            await self.session.flush()
            await self.session.refresh(existing)
            return existing

        row = WizardSession(
            tenant_id=tenant_id,
            session_id=session_id,
            current_step=step,
            collected_requirements=requirements,
            completed=completed,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row


class UseCaseProfileRepository:
    """SQL access for pre-defined use-case requirement profiles."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, tenant_id: UUID, use_case: str) -> UseCaseProfile | None:
        result = await self.session.execute(
            select(UseCaseProfile).where(
                UseCaseProfile.tenant_id == tenant_id,
                UseCaseProfile.use_case == use_case,
            )
        )
        return result.scalar_one_or_none()

    async def list_all(self, tenant_id: UUID) -> list[UseCaseProfile]:
        result = await self.session.execute(
            select(UseCaseProfile).where(UseCaseProfile.tenant_id == tenant_id)
        )
        return list(result.scalars().all())

    async def upsert(self, tenant_id: UUID, use_case: str, requirements: dict[str, Any]) -> UseCaseProfile:
        """Create or update one use-case profile (local-dev seeding)."""
        stmt = insert(UseCaseProfile).values(
            tenant_id=tenant_id, use_case=use_case, requirements=requirements
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[UseCaseProfile.tenant_id, UseCaseProfile.use_case],
            set_={"requirements": stmt.excluded.requirements},
        ).returning(UseCaseProfile)
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.scalar_one()


class SolutionRepository:
    """SQL access for persisted computed solutions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, tenant_id: UUID, session_id: str, solution: Solution) -> Solution:
        """Persist one computed solution, keeping its solution_id stable."""
        row = SolutionRecord(
            id=solution.solution_id,
            tenant_id=tenant_id,
            session_id=session_id,
            use_case=solution.use_case,
            requirements={},
            line_items=[item.model_dump(mode="json") for item in solution.line_items],
            total_estimate=solution.total_estimate,
            currency=solution.currency,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return solution

    async def get(self, tenant_id: UUID, solution_id: UUID) -> Solution | None:
        result = await self.session.execute(
            select(SolutionRecord).where(
                SolutionRecord.tenant_id == tenant_id, SolutionRecord.id == solution_id
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return Solution(
            solution_id=row.id,
            use_case=row.use_case,
            line_items=[BOMLineItem(**item) for item in row.line_items],
            total_estimate=row.total_estimate or 0,
            currency=row.currency,
        )
