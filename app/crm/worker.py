"""Background retry worker for CRM synchronization."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.crm.crm_client import build_crm_service
from app.crm.repository import LeadRepository, RetryQueueRepository
from app.crm.schemas import RetryQueueResult
from app.logging_config import get_logger
from app.observability import registry as metrics

logger = get_logger(__name__)


class RetryWorker:
    """Processes one due CRM retry queue item at a time."""

    def __init__(self, db_session: AsyncSession, settings: Settings) -> None:
        self.leads = LeadRepository(db_session)
        self.queue = RetryQueueRepository(db_session)
        self.crm_service = build_crm_service(settings)
        self.settings = settings

    async def run_once(self) -> RetryQueueResult:
        """Process one due pending queue item."""
        item = await self.queue.get_due_item()
        if item is None:
            return RetryQueueResult(processed=False)

        lead = await self.leads.get(item.tenant_id, item.lead_id)
        if lead is None:
            status = await self.queue.mark_failed(
                item,
                error=f"Lead {item.lead_id} no longer exists",
                max_attempts=self.settings.crm.max_retry_attempts,
            )
            metrics.metrics_registry.increment_crm_sync_result(success=False)
            return RetryQueueResult(processed=True, queue_id=item.id, status=status)

        try:
            await self.crm_service.create_lead(lead)
        except Exception as exc:
            status = await self.queue.mark_failed(
                item,
                error=str(exc),
                max_attempts=self.settings.crm.max_retry_attempts,
            )
            logger.warning("crm_sync_failed", extra={"queue_id": str(item.id), "error": str(exc)})
            metrics.metrics_registry.increment_crm_sync_result(success=False)
            return RetryQueueResult(processed=True, queue_id=item.id, status=status, error=str(exc))

        await self.queue.mark_succeeded(item)
        logger.info("crm_sync_succeeded", extra={"queue_id": str(item.id), "lead_id": str(lead.id)})
        metrics.metrics_registry.increment_crm_sync_result(success=True)
        return RetryQueueResult(processed=True, queue_id=item.id, status="synced")
