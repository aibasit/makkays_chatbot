"""Natural-language product search — a thin wrapper over Module 11's retrieval."""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.rag.retrieval_service import RetrievalService
from app.rag.schemas import ProductResult
from app.session.schemas import ConversationStateSchema, FactsSchema
from app.tools.schemas import ExecutionContext, SessionContext

_SYNTHETIC_SESSION_ID = "nl-search"


class NLSearchService:
    """Delegates natural-language product queries to Module 11's layered retrieval.

    No business logic of its own: builds a synthetic session carrying the query as
    `product_interest` and reuses `RetrievalService.retrieve_products` unchanged.
    """

    def __init__(
        self,
        db_session: AsyncSession,
        settings: Settings,
        *,
        retrieval_service: RetrievalService | None = None,
    ) -> None:
        self.retrieval_service = retrieval_service or RetrievalService(db_session, settings)

    async def search(self, query: str, tenant_id: UUID) -> list[ProductResult]:
        """Return products matching a free-text query."""
        facts = FactsSchema(tenant_id=tenant_id, session_id=_SYNTHETIC_SESSION_ID, product_interest=query)
        state = ConversationStateSchema(tenant_id=tenant_id, session_id=_SYNTHETIC_SESSION_ID)
        session = SessionContext(
            tenant_id=tenant_id,
            session_id=_SYNTHETIC_SESSION_ID,
            facts=facts,
            conversation_state=state,
        )
        result = await self.retrieval_service.retrieve_products(session, ExecutionContext())
        if not result.success or not result.result_summary:
            return []
        return [ProductResult(**item) for item in json.loads(result.result_summary)]
