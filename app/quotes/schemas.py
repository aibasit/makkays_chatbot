"""Quote domain schemas and canonical quote slot predicate."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.session.schemas import ConversationStateSchema, FactsSchema


class QuoteSlots(BaseModel):
    """Validated complete facts required to generate a quote."""

    company: str
    product_ids: list[UUID] = Field(min_length=1)
    quantity: int = Field(gt=0)
    budget: Decimal = Field(ge=0)


class QuoteLineItem(BaseModel):
    """One deterministic quote line item."""

    product_id: UUID
    name: str
    unit_price: Decimal = Field(ge=0)
    quantity: int = Field(gt=0)
    subtotal: Decimal = Field(ge=0)

    @field_validator("unit_price", "subtotal")
    @classmethod
    def normalize_money(cls, value: Decimal) -> Decimal:
        """Store money-like values with two decimal places."""
        return value.quantize(Decimal("0.01"))


class QuoteResult(BaseModel):
    """Completed persisted quote result."""

    quote_id: UUID
    company: str
    line_items: list[QuoteLineItem] = Field(min_length=1)
    total: Decimal = Field(ge=0)
    currency: str = "USD"
    pdf_generated: bool = False

    @field_validator("total")
    @classmethod
    def normalize_total(cls, value: Decimal) -> Decimal:
        """Store total with two decimal places."""
        return value.quantize(Decimal("0.01"))

    def deterministic_summary(self) -> str:
        """Return a no-LLM fallback summary of the completed quote."""
        return (
            f"Quote {self.quote_id} for {self.company}: "
            f"{self.currency} {self.total} across {len(self.line_items)} line item(s)."
        )


def quote_slots_complete(facts: FactsSchema, state: ConversationStateSchema | None = None) -> bool:
    """Return whether enough facts exist to generate a quote.

    Accepts (and ignores) `state` so the signature matches the uniform
    `(facts, state) -> bool` shape Module 10's `PREDICATE_REGISTRY` requires.
    """
    return bool(
        facts.company is not None
        and facts.product_interest is not None
        and facts.quantity is not None
        and facts.budget is not None
    )
