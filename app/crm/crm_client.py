"""CRM provider adapters."""

from __future__ import annotations

import httpx

from app.config import Settings
from app.crm.models import Lead


class LocalCRMService:
    """Local provider: the lead already lives in PostgreSQL, so sync succeeds."""

    async def create_lead(self, lead: Lead) -> None:
        """No-op sync for local CRM mode."""
        return None


class HttpCRMService:
    """Minimal HTTP CRM adapter for future external providers."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def create_lead(self, lead: Lead) -> None:
        """POST a lead payload to the configured CRM endpoint."""
        payload = {
            "id": str(lead.id),
            "tenant_id": str(lead.tenant_id),
            "session_id": lead.session_id,
            "contact_name": lead.contact_name,
            "contact_email": lead.contact_email,
            "contact_phone": lead.contact_phone,
            "company": lead.company,
            "product_interest": lead.product_interest,
            "qualification": lead.qualification,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{self.settings.crm.base_url.rstrip('/')}/leads",
                headers={"Authorization": f"Bearer {self.settings.crm.api_key.get_secret_value()}"},
                json=payload,
            )
            response.raise_for_status()


def build_crm_service(settings: Settings) -> LocalCRMService | HttpCRMService:
    """Return the configured CRM provider adapter."""
    if settings.crm.provider.lower() == "local":
        return LocalCRMService()
    return HttpCRMService(settings)
