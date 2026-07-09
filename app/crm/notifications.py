"""Email notification helpers for leads and quotes."""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from app.config import Settings
from app.crm.schemas import LeadRead
from app.handoff.schemas import HandoffRead
from app.quotes.schemas import QuoteResult
from app.session.schemas import FactsSchema

logger = logging.getLogger(__name__)


class NotificationService:
    """Thin Resend REST client with no-op behavior when credentials are absent."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def send_lead_notification(self, lead: LeadRead) -> bool:
        """Notify sales that a lead was captured."""
        subject = f"New chatbot lead: {lead.company or lead.contact_name or lead.id}"
        lines = [
            "A new lead was captured by the AI Sales Engineer.",
            f"Lead ID: {lead.id}",
            f"Company: {lead.company or 'Unknown'}",
            f"Contact: {lead.contact_name or 'Unknown'}",
            f"Email: {lead.contact_email or 'Not provided'}",
            f"Phone: {lead.contact_phone or 'Not provided'}",
            f"Product interest: {lead.product_interest or 'Not provided'}",
        ]
        return await self._send_email(
            to=self.settings.resend.from_email,
            subject=subject,
            text="\n".join(lines),
        )

    async def send_quote_pdf(
        self,
        *,
        to_email: str,
        quote: QuoteResult,
        pdf_bytes: bytes,
    ) -> bool:
        """Email a generated quote PDF to a customer."""
        attachment = {
            "filename": f"quote-{quote.quote_id}.pdf",
            "content": base64.b64encode(pdf_bytes).decode("ascii"),
        }
        return await self._send_email(
            to=to_email,
            subject=f"Quote {quote.quote_id} for {quote.company}",
            text=quote.deterministic_summary(),
            attachments=[attachment],
        )

    async def send_handoff_notification(self, handoff: HandoffRead, facts: FactsSchema) -> bool:
        """Notify the selected internal team about a human handoff."""
        subject = f"Chat handoff {handoff.reference_id}: {handoff.target_team}"
        lines = [
            "A customer requested human handoff from the AI Sales Engineer.",
            f"Reference: {handoff.reference_id}",
            f"Team: {handoff.target_team}",
            f"Status: {handoff.status}",
            f"Company: {facts.company or 'Unknown'}",
            f"Contact: {handoff.contact_name or 'Unknown'}",
            f"Email: {handoff.contact_email or 'Not provided'}",
            f"Phone: {handoff.contact_phone or 'Not provided'}",
            f"Product interest: {facts.product_interest or 'Not provided'}",
            f"Industry: {facts.industry or 'Not provided'}",
            f"Project size: {facts.project_size or 'Not provided'}",
            f"Location: {getattr(facts, 'location', None) or 'Not provided'}",
            f"Timeline: {getattr(facts, 'timeline', None) or 'Not provided'}",
            "",
            "Conversation:",
            *format_handoff_transcript(handoff),
        ]
        return await self._send_email(
            to=self.settings.resend.from_email,
            subject=subject,
            text="\n".join(lines),
        )

    async def _send_email(
        self,
        *,
        to: str,
        subject: str,
        text: str,
        attachments: list[dict[str, str]] | None = None,
    ) -> bool:
        api_key = self.settings.resend.api_key.get_secret_value()
        if not api_key or api_key.lower().startswith(("dummy", "test", "mock")):
            logger.info("resend_email_skipped_mock_key", extra={"subject": subject, "to": to})
            return False

        payload: dict[str, Any] = {
            "from": self.settings.resend.from_email,
            "to": [to],
            "subject": subject,
            "text": text,
        }
        if attachments:
            payload["attachments"] = attachments

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=payload,
                )
                response.raise_for_status()
        except Exception as exc:
            logger.warning("resend_email_failed", extra={"subject": subject, "error": str(exc)})
            return False
        logger.info("resend_email_sent", extra={"subject": subject, "to": to})
        return True


def format_handoff_transcript(handoff: HandoffRead) -> list[str]:
    """Render a compact text transcript from the stored export."""
    lines: list[str] = []
    for item in handoff.conversation_export:
        role = str(item.get("role", "unknown")).upper()
        content = str(item.get("content", "")).strip()
        if content:
            lines.append(f"{role}: {content}")
    return lines or ["No prior turns were available."]
