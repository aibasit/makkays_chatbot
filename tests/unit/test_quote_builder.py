"""Unit tests for Module 12 Quote Builder."""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.llm.schemas import LLMResponse
from app.quotes.builder import QuoteBuilder, QuoteExplainer
from app.quotes.exceptions import IncompleteQuoteSlotsError, PricingDataMissingError
from app.quotes.schemas import QuoteResult
from app.session.schemas import ConversationStateSchema, FactsSchema
from app.tools.schemas import ExecutionContext, SessionContext, ToolExecutionResult


class FakePricingRepository:
    def __init__(self, prices: dict[uuid.UUID, tuple[Decimal, str]]) -> None:
        self.prices = prices

    async def get_prices(
        self,
        tenant_id: uuid.UUID,
        product_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, Any]:
        return {
            product_id: SimpleNamespace(product_id=product_id, unit_price=price, currency=currency)
            for product_id, (price, currency) in self.prices.items()
            if product_id in product_ids
        }


class FakeProductRepository:
    def __init__(self, names: dict[uuid.UUID, str]) -> None:
        self.names = names

    async def get_by_ids(
        self,
        tenant_id: uuid.UUID,
        product_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, Any]:
        return {
            product_id: SimpleNamespace(id=product_id, name=self.names[product_id])
            for product_id in product_ids
            if product_id in self.names
        }


class FakeQuoteRepository:
    def __init__(self, quote_id: uuid.UUID | None = None) -> None:
        self.quote_id = quote_id or uuid.uuid4()
        self.created: dict[str, Any] | None = None

    async def create(self, **kwargs: Any) -> Any:
        self.created = kwargs
        return SimpleNamespace(id=self.quote_id)


class FakePromptProvider:
    def get(self, category: str, name: str, version: str) -> str:
        return "Narrate the computed quote. Never recompute or alter numbers."


class FakeLLMClient:
    def __init__(self) -> None:
        self.messages: list[Any] = []
        self.calls = 0

    async def chat(self, messages: list[Any], **kwargs: Any) -> LLMResponse:
        self.calls += 1
        self.messages = messages
        return LLMResponse(content="Your computed quote total is USD 1000.00.")


def _session(tenant_id: uuid.UUID, *, complete: bool = True) -> SessionContext:
    return SessionContext(
        tenant_id=tenant_id,
        session_id="s1",
        facts=FactsSchema(
            tenant_id=tenant_id,
            session_id="s1",
            company="Acme" if complete else None,
            product_interest="switch",
            quantity=2,
            budget=Decimal("5000"),
        ),
        conversation_state=ConversationStateSchema(tenant_id=tenant_id, session_id="s1"),
    )


def _context(product_ids: list[uuid.UUID] | None) -> ExecutionContext:
    return ExecutionContext(
        retrieve_products=ToolExecutionResult(
            step="retrieve_products",
            success=bool(product_ids),
            result_summary="",
            product_ids=product_ids,
        )
        if product_ids is not None
        else None
    )


@pytest.mark.asyncio
async def test_quote_builder_computes_correct_subtotals_and_total() -> None:
    tenant_id = uuid.uuid4()
    product_a = uuid.uuid4()
    product_b = uuid.uuid4()
    quote_repo = FakeQuoteRepository()
    builder = QuoteBuilder(
        db_session=None,  # type: ignore[arg-type]
        pricing_repository=FakePricingRepository(
            {product_a: (Decimal("100.00"), "USD"), product_b: (Decimal("400.00"), "USD")}
        ),  # type: ignore[arg-type]
        product_repository=FakeProductRepository(
            {product_a: "Switch A", product_b: "Switch B"}
        ),  # type: ignore[arg-type]
        quote_repository=quote_repo,  # type: ignore[arg-type]
    )

    result = await builder.build(_session(tenant_id), _context([product_a, product_b]))

    assert result.quote_id == quote_repo.quote_id
    assert [item.subtotal for item in result.line_items] == [Decimal("200.00"), Decimal("800.00")]
    assert result.total == Decimal("1000.00")
    assert quote_repo.created is not None
    assert quote_repo.created["total"] == Decimal("1000.00")


@pytest.mark.asyncio
async def test_quote_builder_raises_on_incomplete_slots() -> None:
    builder = QuoteBuilder(
        db_session=None,  # type: ignore[arg-type]
        pricing_repository=FakePricingRepository({}),  # type: ignore[arg-type]
        product_repository=FakeProductRepository({}),  # type: ignore[arg-type]
        quote_repository=FakeQuoteRepository(),  # type: ignore[arg-type]
    )

    with pytest.raises(IncompleteQuoteSlotsError):
        await builder.build(_session(uuid.uuid4(), complete=False), _context([uuid.uuid4()]))


@pytest.mark.asyncio
async def test_quote_builder_raises_on_missing_pricing() -> None:
    product_id = uuid.uuid4()
    builder = QuoteBuilder(
        db_session=None,  # type: ignore[arg-type]
        pricing_repository=FakePricingRepository({}),  # type: ignore[arg-type]
        product_repository=FakeProductRepository({product_id: "Switch"}),  # type: ignore[arg-type]
        quote_repository=FakeQuoteRepository(),  # type: ignore[arg-type]
    )

    with pytest.raises(PricingDataMissingError) as exc_info:
        await builder.build(_session(uuid.uuid4()), _context([product_id]))

    assert exc_info.value.missing_product_ids == [product_id]


@pytest.mark.asyncio
async def test_quote_explainer_never_recomputes_numbers() -> None:
    quote = QuoteResult(
        quote_id=uuid.uuid4(),
        company="Acme",
        line_items=[
            {
                "product_id": uuid.uuid4(),
                "name": "Switch",
                "unit_price": Decimal("500.00"),
                "quantity": 2,
                "subtotal": Decimal("1000.00"),
            }
        ],
        total=Decimal("1000.00"),
        currency="USD",
    )
    llm = FakeLLMClient()
    explainer = QuoteExplainer()

    explanation = await explainer.explain(quote, llm, FakePromptProvider())

    assert explanation == "Your computed quote total is USD 1000.00."
    assert llm.calls == 1
    assert "Never recompute" in llm.messages[0].content
    assert str(quote.total) in llm.messages[1].content
