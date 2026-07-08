"""Unit tests for Module 14 CRM lead service."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.crm.service import LeadService
from app.session.schemas import ConversationStateSchema, FactsSchema
from app.tools.schemas import ExecutionContext, SessionContext, ToolExecutionResult


class FakeLeadRepository:
    def __init__(self) -> None:
        self.created: Any = None
        self.lead_id = uuid.uuid4()

    async def create(self, lead: Any) -> Any:
        self.created = lead
        return SimpleNamespace(
            id=self.lead_id,
            tenant_id=lead.tenant_id,
            session_id=lead.session_id,
            contact_name=lead.contact_name,
            contact_email=lead.contact_email,
            contact_phone=lead.contact_phone,
            company=lead.company,
            product_interest=lead.product_interest,
            message=lead.message,
            status="new",
            qualification=lead.qualification,
            facts_snapshot=lead.facts_snapshot,
            created_at=datetime.now(timezone.utc),
        )


class FakeRetryQueueRepository:
    def __init__(self) -> None:
        self.enqueued: dict[str, Any] | None = None
        self.queue_id = uuid.uuid4()

    async def enqueue(self, **kwargs: Any) -> Any:
        self.enqueued = kwargs
        return SimpleNamespace(id=self.queue_id)


class FakeNotificationService:
    async def send_lead_notification(self, lead: Any) -> bool:
        return True


def _session(tenant_id: uuid.UUID) -> SessionContext:
    return SessionContext(
        tenant_id=tenant_id,
        session_id="session-1",
        facts=FactsSchema(
            tenant_id=tenant_id,
            session_id="session-1",
            company="Acme",
            product_interest="switches",
            quantity=10,
            budget=Decimal("5000"),
            contact_name="Ayesha",
            contact_email="Ayesha@Example.com",
        ),
        conversation_state=ConversationStateSchema(tenant_id=tenant_id, session_id="session-1"),
    )


@pytest.mark.asyncio
async def test_lead_service_creates_lead_and_retry_queue() -> None:
    tenant_id = uuid.uuid4()
    lead_repo = FakeLeadRepository()
    retry_repo = FakeRetryQueueRepository()
    service = LeadService(
        db_session=None,  # type: ignore[arg-type]
        lead_repository=lead_repo,  # type: ignore[arg-type]
        retry_repository=retry_repo,  # type: ignore[arg-type]
        notification_service=FakeNotificationService(),  # type: ignore[arg-type]
    )
    service._notify_later = lambda lead: None  # type: ignore[method-assign]
    context = ExecutionContext(
        generate_quote=ToolExecutionResult(
            step="generate_quote",
            success=True,
            result_summary="Quote total is USD 4500.",
        )
    )

    result = await service.create_lead(_session(tenant_id), context)

    assert result.lead_id == lead_repo.lead_id
    assert result.retry_queue_id == retry_repo.queue_id
    assert lead_repo.created.contact_email == "ayesha@example.com"
    assert lead_repo.created.message == "Quote total is USD 4500."
    assert retry_repo.enqueued is not None
    assert retry_repo.enqueued["lead_id"] == lead_repo.lead_id


@pytest.mark.asyncio
async def test_lead_service_requires_contact_method() -> None:
    tenant_id = uuid.uuid4()
    session = _session(tenant_id)
    session = session._replace(
        facts=session.facts.model_copy(update={"contact_email": None, "contact_phone": None})
    )
    service = LeadService(
        db_session=None,  # type: ignore[arg-type]
        lead_repository=FakeLeadRepository(),  # type: ignore[arg-type]
        retry_repository=FakeRetryQueueRepository(),  # type: ignore[arg-type]
        notification_service=FakeNotificationService(),  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="contact_email or contact_phone"):
        await service.create_lead(session, ExecutionContext())
