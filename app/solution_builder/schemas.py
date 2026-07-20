"""Pydantic schemas for the wizard, BOM, and solution outputs."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.session.schemas import ConversationStateSchema, FactsSchema


class ProjectScale(BaseModel):
    """Deployment scale and the pricing mode it implies."""

    size: Literal["small", "medium", "large", "enterprise"]
    pricing_mode: Literal["calculated", "call_for_pricing"]
    reason: str


class WizardRequirements(BaseModel):
    """Requirements collected across the 5-step wizard.

    No budget field: pricing is either calculated deterministically from
    `product_pricing`, or routed to `call_for_pricing` — never a user-supplied
    number that could contradict the catalogue or an enterprise quotation.
    """

    use_case: str | None = None
    device_count: int | None = None
    project_size: ProjectScale | None = None
    location: str | None = None
    brand_preference: str | None = None
    # A stated power/capacity requirement (e.g. "20kVA"), recovered from the
    # conversation via app.rag.capacity.parse_capacity_requirement — the wizard's
    # own questions never ask for this directly, but a visitor typically states
    # it in the message that triggered the wizard in the first place. Without
    # it, the "ups" line item can only grab an arbitrary product from the
    # category rather than one actually sized for the visitor's load.
    capacity_requirement: Decimal | None = None
    capacity_unit: str | None = None


class BOMLineItem(BaseModel):
    """One deterministic bill-of-materials line item."""

    category: str
    product_id: UUID
    product_name: str
    quantity: int = Field(gt=0)
    unit_price: Decimal = Field(ge=0)
    subtotal: Decimal = Field(ge=0)


class Solution(BaseModel):
    """A computed (or narrated) solution: line items plus a deterministic total."""

    solution_id: UUID
    use_case: str | None
    line_items: list[BOMLineItem]
    total_estimate: Decimal
    currency: str = "USD"
    narration: str = ""


class UseCaseSolution(BaseModel):
    """Result of mapping a use case to a solution."""

    use_case: str
    solution: Solution
    profile_used: bool


class CallForPricingResult(BaseModel):
    """Result of routing a large/enterprise wizard completion to sales."""

    reference_id: str
    scale: ProjectScale
    requirements_summary: str
    message: str
    lead_id: UUID


class WizardStep(BaseModel):
    """One turn's wizard state: either the next question, or the completed outcome."""

    step_number: int
    question_text: str | None = None
    is_complete: bool
    solution: Solution | None = None
    call_for_pricing: CallForPricingResult | None = None


def solution_slots_complete(facts: FactsSchema, state: ConversationStateSchema | None = None) -> bool:
    """Return whether enough facts exist to build a solution directly, without the wizard.

    Accepts (and ignores) `state` so the signature matches the uniform
    `(facts, state) -> bool` shape used by `quote_slots_complete`.
    """
    return bool(facts.product_interest is not None and facts.quantity is not None)
