"""Unit tests for Module 18 NLSearchService."""

from __future__ import annotations

import json
import uuid

import pytest

from app.product_intelligence.nl_search_service import NLSearchService
from app.tools.schemas import ExecutionContext, SessionContext, ToolExecutionResult


class FakeRetrievalService:
    def __init__(self, result: ToolExecutionResult) -> None:
        self.result = result
        self.calls: list[tuple[SessionContext, ExecutionContext]] = []

    async def retrieve_products(self, session: SessionContext, context: ExecutionContext) -> ToolExecutionResult:
        self.calls.append((session, context))
        return self.result


@pytest.mark.asyncio
async def test_nl_search_delegates_to_retrieval_service() -> None:
    product_id = uuid.uuid4()
    fake_result = ToolExecutionResult(
        step="retrieve_products",
        success=True,
        result_summary=json.dumps(
            [{"product_id": str(product_id), "name": "Switch A", "brand": "Acme", "category": "switch", "score": 0.9}]
        ),
        product_ids=[product_id],
    )
    retrieval_service = FakeRetrievalService(fake_result)
    service = NLSearchService(db_session=None, settings=None, retrieval_service=retrieval_service)  # type: ignore[arg-type]

    results = await service.search("48-port switch", uuid.uuid4())

    assert len(retrieval_service.calls) == 1
    session, _context = retrieval_service.calls[0]
    assert session.facts.product_interest == "48-port switch"
    assert len(results) == 1
    assert results[0].product_id == product_id
    assert results[0].name == "Switch A"


@pytest.mark.asyncio
async def test_nl_search_returns_empty_list_when_retrieval_fails() -> None:
    fake_result = ToolExecutionResult(step="retrieve_products", success=False, result_summary="", error="boom")
    service = NLSearchService(
        db_session=None,  # type: ignore[arg-type]
        settings=None,  # type: ignore[arg-type]
        retrieval_service=FakeRetrievalService(fake_result),
    )

    results = await service.search("anything", uuid.uuid4())

    assert results == []
