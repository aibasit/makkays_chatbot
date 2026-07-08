"""Deterministic quote generation, PDF export, and LLM narration."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from io import BytesIO
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_sessionmaker
from app.dependencies import get_settings
from app.llm.context import build_llm_messages
from app.llm.factory import get_llm_client
from app.llm.schemas import LLMClientProtocol
from app.logging_config import get_logger
from app.observability import registry as metrics
from app.prompts.manager import PromptProvider, prompt_manager
from app.quotes.exceptions import (
    IncompleteQuoteSlotsError,
    PricingDataMissingError,
    QuoteCurrencyMismatchError,
)
from app.quotes.repository import ProductPricingRepository, QuoteRepository
from app.quotes.schemas import QuoteLineItem, QuoteResult, QuoteSlots, quote_slots_complete
from app.rag.repository import ProductRepository
from app.tools.schemas import ExecutionContext, SessionContext, ToolExecutionResult

logger = get_logger(__name__)


class QuoteBuilder:
    """Builds and persists deterministic quotes. Never calls an LLM."""

    def __init__(
        self,
        db_session: AsyncSession,
        *,
        pricing_repository: ProductPricingRepository | None = None,
        quote_repository: QuoteRepository | None = None,
        product_repository: ProductRepository | None = None,
    ) -> None:
        self.pricing_repository = pricing_repository or ProductPricingRepository(db_session)
        self.quote_repository = quote_repository or QuoteRepository(db_session)
        self.product_repository = product_repository or ProductRepository(db_session)

    async def build(self, session: SessionContext, context: ExecutionContext) -> QuoteResult:
        """Compute quote numbers from SQL prices and persist the result."""
        try:
            slots = self._build_slots(session, context)
            prices = await self.pricing_repository.get_prices(session.tenant_id, slots.product_ids)
            missing = [product_id for product_id in slots.product_ids if product_id not in prices]
            if missing:
                raise PricingDataMissingError(missing)

            currencies = {prices[product_id].currency for product_id in slots.product_ids}
            if len(currencies) != 1:
                raise QuoteCurrencyMismatchError("All quote line items must use one currency")
            currency = next(iter(currencies))

            products = await self.product_repository.get_by_ids(session.tenant_id, slots.product_ids)
            line_items = [
                QuoteLineItem(
                    product_id=product_id,
                    name=products[product_id].name if product_id in products else str(product_id),
                    unit_price=Decimal(prices[product_id].unit_price),
                    quantity=slots.quantity,
                    subtotal=Decimal(prices[product_id].unit_price) * slots.quantity,
                )
                for product_id in slots.product_ids
            ]
            total = sum((item.subtotal for item in line_items), Decimal("0.00"))
            quote = await self.quote_repository.create(
                tenant_id=session.tenant_id,
                session_id=session.session_id,
                company=slots.company,
                line_items=line_items,
                total=total,
                currency=currency,
            )
            result = QuoteResult(
                quote_id=quote.id,
                company=slots.company,
                line_items=line_items,
                total=total,
                currency=currency,
            )
            logger.info(
                "quote_built",
                extra={
                    "tenant_id": str(session.tenant_id),
                    "session_id": session.session_id,
                    "quote_id": str(result.quote_id),
                    "product_count": len(line_items),
                    "total": str(result.total),
                    "currency": result.currency,
                },
            )
            metrics.metrics_registry.increment_quote_result(success=True)
            return result
        except Exception:
            metrics.metrics_registry.increment_quote_result(success=False)
            raise

    @staticmethod
    def _build_slots(session: SessionContext, context: ExecutionContext) -> QuoteSlots:
        product_ids = context.get_product_ids()
        if not product_ids:
            raise IncompleteQuoteSlotsError("product_ids unavailable in ExecutionContext")
        if not quote_slots_complete(session.facts):
            raise IncompleteQuoteSlotsError("Quote slots are incomplete")
        assert session.facts.company is not None
        assert session.facts.quantity is not None
        assert session.facts.budget is not None
        return QuoteSlots(
            company=session.facts.company,
            product_ids=product_ids,
            quantity=session.facts.quantity,
            budget=session.facts.budget,
        )


class QuoteExplainer:
    """LLM narration for an already-computed QuoteResult."""

    async def explain(
        self,
        quote_result: QuoteResult,
        llm_client: LLMClientProtocol,
        prompt_provider: PromptProvider,
    ) -> str:
        """Ask the LLM to restate the quote without changing any numbers."""
        system_prompt = prompt_provider.get("quotes", "quote_explanation", "1")
        messages, _metadata = build_llm_messages(
            system_prompt=system_prompt,
            quote_summary=quote_result.model_dump(mode="json"),
            latest_user_message="Restate this computed quote for the customer. Do not recalculate.",
        )
        response = await llm_client.chat(messages=messages, temperature=0.3)
        return response.content or quote_result.deterministic_summary()


class QuotePDFGenerator:
    """Generate a simple PDF from a completed QuoteResult."""

    def generate(self, quote: QuoteResult) -> bytes:
        """Return PDF bytes. All numbers come from the precomputed quote."""
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import letter
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
        except Exception as exc:
            raise RuntimeError("reportlab is required for quote PDF generation") from exc

        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        styles = getSampleStyleSheet()
        rows: list[list[Any]] = [["Product", "Qty", "Unit Price", "Subtotal"]]
        for item in quote.line_items:
            rows.append(
                [
                    item.name,
                    str(item.quantity),
                    f"{quote.currency} {item.unit_price}",
                    f"{quote.currency} {item.subtotal}",
                ]
            )
        rows.append(["Grand Total", "", "", f"{quote.currency} {quote.total}"])
        table = Table(rows, hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ]
            )
        )
        story = [
            Paragraph(f"Quote for {quote.company}", styles["Title"]),
            Paragraph(f"Quote ID: {quote.quote_id}", styles["Normal"]),
            Spacer(1, 12),
            table,
            Spacer(1, 24),
            Paragraph("Makkays quote generated by AI Sales Engineer.", styles["Italic"]),
        ]
        doc.build(story)
        return buffer.getvalue()


async def generate_quote_tool(
    session: SessionContext,
    context: ExecutionContext,
) -> ToolExecutionResult:
    """Module 10 tool entrypoint for quote generation."""
    settings = get_settings()
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db_session:
        builder = QuoteBuilder(db_session)
        quote_result = await builder.build(session, context)
        pdf_bytes = await _generate_and_save_pdf(db_session, session, quote_result)
        await db_session.commit()

    explainer = QuoteExplainer()
    try:
        explanation = await explainer.explain(
            quote_result,
            get_llm_client(settings),
            prompt_manager,
        )
    except Exception as exc:
        logger.warning(
            "quote_explainer_failed",
            extra={"quote_id": str(quote_result.quote_id), "error": str(exc)},
        )
        explanation = quote_result.deterministic_summary()

    _maybe_notify_quote_generated(session, quote_result, pdf_bytes)
    return ToolExecutionResult(step="generate_quote", success=True, result_summary=explanation)


async def _generate_and_save_pdf(
    db_session: AsyncSession,
    session: SessionContext,
    quote_result: QuoteResult,
) -> bytes:
    generator = QuotePDFGenerator()
    try:
        pdf_bytes = await asyncio.get_running_loop().run_in_executor(
            None,
            generator.generate,
            quote_result,
        )
        repository = QuoteRepository(db_session)
        await repository.save_pdf(session.tenant_id, quote_result.quote_id, pdf_bytes)
        quote_result.pdf_generated = True
        metrics.metrics_registry.increment_quote_pdf_generated(success=True)
        return pdf_bytes
    except Exception:
        metrics.metrics_registry.increment_quote_pdf_generated(success=False)
        raise


def _maybe_notify_quote_generated(
    session: SessionContext,
    quote_result: QuoteResult,
    pdf_bytes: bytes,
) -> None:
    """Send quote email in the background when contact email is known."""
    if not session.facts.contact_email:
        logger.debug(
            "quote_email_skipped_no_contact_email",
            extra={"quote_id": str(quote_result.quote_id)},
        )
        return
    try:
        from app.crm.notifications import NotificationService

        settings = get_settings()
        notifier = NotificationService(settings)

        async def _send() -> None:
            try:
                await notifier.send_quote_pdf(
                    to_email=session.facts.contact_email or "",
                    quote=quote_result,
                    pdf_bytes=pdf_bytes,
                )
            except Exception as exc:
                logger.warning(
                    "quote_email_failed",
                    extra={"quote_id": str(quote_result.quote_id), "error": str(exc)},
                )

        asyncio.create_task(_send())
    except RuntimeError:
        logger.debug("quote_email_skipped_no_running_loop", extra={"quote_id": str(quote_result.quote_id)})
