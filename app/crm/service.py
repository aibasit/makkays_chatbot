"""CRM lead capture service and Module 10 tool entrypoint."""

from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.crm.notifications import NotificationService
from app.crm.repository import LeadRepository, RetryQueueRepository
from app.crm.schemas import LeadCreate, LeadRead, LeadResult
from app.dependencies import get_settings
from app.logging_config import get_logger
from app.observability import registry as metrics
from app.session.schemas import FactsSchema
from app.tools.schemas import ExecutionContext, SessionContext, ToolExecutionResult

logger = get_logger(__name__)


class LeadService:
    """Create leads from captured session facts and queue CRM sync."""

    def __init__(
        self,
        db_session: AsyncSession,
        *,
        lead_repository: LeadRepository | None = None,
        retry_repository: RetryQueueRepository | None = None,
        notification_service: NotificationService | None = None,
    ) -> None:
        self.lead_repository = lead_repository or LeadRepository(db_session)
        self.retry_repository = retry_repository or RetryQueueRepository(db_session)
        self.notification_service = notification_service or NotificationService(get_settings())

    async def create_lead(
        self,
        session: SessionContext,
        context: ExecutionContext,
    ) -> LeadResult:
        """Persist a lead, enqueue CRM sync, and trigger non-blocking notification."""
        if not (session.facts.contact_email or session.facts.contact_phone):
            raise ValueError("Lead creation requires contact_email or contact_phone")

        lead_create = self._build_lead_create(session, context)
        lead = await self.lead_repository.create(lead_create)
        lead_read = LeadRead.model_validate(lead)
        queue_item = await self.retry_repository.enqueue(
            tenant_id=session.tenant_id,
            lead_id=lead.id,
            payload=lead_read.model_dump(mode="json"),
        )
        self._notify_later(lead_read)
        summary = (
            f"Created lead {lead.id} for "
            f"{lead.company or lead.contact_name or lead.contact_email or lead.contact_phone}."
        )
        logger.info(
            "lead_created",
            extra={
                "tenant_id": str(session.tenant_id),
                "session_id": session.session_id,
                "lead_id": str(lead.id),
                "retry_queue_id": str(queue_item.id),
            },
        )
        metrics.metrics_registry.increment_lead_created()
        return LeadResult(lead_id=lead.id, retry_queue_id=queue_item.id, summary=summary)

    def _build_lead_create(self, session: SessionContext, context: ExecutionContext) -> LeadCreate:
        facts = session.facts
        quote_summary = context.generate_quote.result_summary if context.generate_quote else None
        return LeadCreate(
            tenant_id=session.tenant_id,
            session_id=session.session_id,
            contact_name=facts.contact_name,
            contact_email=facts.contact_email,
            contact_phone=facts.contact_phone,
            company=facts.company,
            product_interest=facts.product_interest,
            message=quote_summary,
            qualification=_qualification_from_facts(facts),
            facts_snapshot=facts.model_dump(mode="json"),
        )

    def _notify_later(self, lead: LeadRead) -> None:
        async def _send() -> None:
            try:
                await self.notification_service.send_lead_notification(lead)
            except Exception as exc:
                logger.warning("lead_notification_failed", extra={"lead_id": str(lead.id), "error": str(exc)})

        try:
            asyncio.create_task(_send())
        except RuntimeError:
            logger.debug("lead_notification_skipped_no_running_loop", extra={"lead_id": str(lead.id)})


async def create_lead_tool(
    session: SessionContext,
    context: ExecutionContext,
) -> ToolExecutionResult:
    """Module 10 tool entrypoint for CRM lead creation."""
    from app.db.engine import get_sessionmaker

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db_session:
        service = LeadService(db_session)
        result = await service.create_lead(session, context)
        await db_session.commit()
    return ToolExecutionResult(step="create_lead", success=True, result_summary=result.summary)


def _qualification_from_facts(facts: FactsSchema) -> dict[str, Any]:
    return {
        "budget": str(facts.budget) if facts.budget is not None else None,
        "quantity": facts.quantity,
        "industry": facts.industry,
        "project_size": facts.project_size,
    }
