"""Routes large/enterprise wizard completions to a human sales engineer.

Called instead of `BOMService.build` whenever `ScaleClassifier.classify` returns
`pricing_mode='call_for_pricing'` — catalogue pricing can't reflect volume
discounts, custom SLAs, or bundled support for projects at this scale.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.crm.notifications import NotificationService
from app.crm.repository import LeadRepository, RetryQueueRepository
from app.crm.schemas import LeadCreate, LeadRead
from app.dependencies import get_settings
from app.logging_config import get_logger
from app.solution_builder.schemas import CallForPricingResult, ProjectScale, WizardRequirements

logger = get_logger(__name__)

_HANDOFF_NOTE = "Large/Enterprise wizard — call for pricing"


class CallForPricingService:
    """Creates a qualified CRM lead and hands off to sales instead of computing a BOM total."""

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

    async def handle(
        self,
        requirements: WizardRequirements,
        scale: ProjectScale,
        tenant_id: UUID,
        session_id: str,
    ) -> CallForPricingResult:
        """Create the CRM lead, fire the sales notification, and return the user-facing result."""
        requirements_summary = _summarize(requirements)
        lead_create = LeadCreate(
            tenant_id=tenant_id,
            session_id=session_id,
            product_interest=requirements.use_case,
            message=_HANDOFF_NOTE,
            qualification={
                "project_size": scale.size,
                "device_count": requirements.device_count,
                "use_case": requirements.use_case,
                "location": requirements.location,
                "brand_preference": requirements.brand_preference,
                "reason": scale.reason,
            },
        )
        lead = await self.lead_repository.create(lead_create)
        lead_read = LeadRead.model_validate(lead)
        await self.retry_repository.enqueue(
            tenant_id=tenant_id, lead_id=lead.id, payload=lead_read.model_dump(mode="json")
        )
        self._notify_later(lead_read)

        reference_id = _reference_id()
        message = _render_message(reference_id, requirements, scale, requirements_summary)
        logger.info(
            "call_for_pricing_handoff",
            extra={"tenant_id": str(tenant_id), "lead_id": str(lead.id), "reference_id": reference_id},
        )
        return CallForPricingResult(
            reference_id=reference_id,
            scale=scale,
            requirements_summary=requirements_summary,
            message=message,
            lead_id=lead.id,
        )

    def _notify_later(self, lead: LeadRead) -> None:
        async def _send() -> None:
            try:
                await self.notification_service.send_lead_notification(lead)
            except Exception as exc:
                logger.warning("call_for_pricing_notification_failed", extra={"lead_id": str(lead.id), "error": str(exc)})

        try:
            asyncio.create_task(_send())
        except RuntimeError:
            logger.debug("call_for_pricing_notification_skipped_no_running_loop", extra={"lead_id": str(lead.id)})


def _reference_id() -> str:
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"CFP-{date_part}-{uuid4().hex[:6].upper()}"


def _summarize(requirements: WizardRequirements) -> str:
    parts = []
    if requirements.use_case:
        parts.append(f"use case: {requirements.use_case}")
    if requirements.device_count:
        parts.append(f"{requirements.device_count} devices")
    if requirements.location:
        parts.append(f"location: {requirements.location}")
    if requirements.brand_preference:
        parts.append(f"brand preference: {requirements.brand_preference}")
    return ", ".join(parts) if parts else "no details collected yet"


def _render_message(
    reference_id: str,
    requirements: WizardRequirements,
    scale: ProjectScale,
    requirements_summary: str,
) -> str:
    device_count = requirements.device_count or 0
    use_case = requirements.use_case or "your"
    return (
        "Thank you for sharing your requirements. Based on the scale of your project "
        f"({device_count}+ devices, {use_case} deployment), our standard pricing "
        "catalogue doesn't fully reflect the volume discounts, installation services, "
        "and support packages available for projects of this size.\n\n"
        f"I've created a priority inquiry for our enterprise sales team. Reference: "
        f"{reference_id}. A sales engineer will contact you within 1 business day to "
        "discuss a custom quotation.\n\n"
        f"What you've shared so far: {requirements_summary}"
    )
