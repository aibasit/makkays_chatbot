"""Unit tests for Module 11 RetrievalService with fake collaborators."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from app.config import EmbeddingSettings, QdrantSettings, RagSettings
from app.rag.embeddings import BGE_M3_VECTOR_SIZE, BgeM3Embedder
from app.rag.filter_extraction import FilterExtractor
from app.rag.retrieval_service import RetrievalService
from app.rag.schemas import ExtractedFilters
from app.session.schemas import ConversationStateSchema, FactsSchema
from app.tools.schemas import ExecutionContext, SessionContext, ToolExecutionResult


class FakeEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * BGE_M3_VECTOR_SIZE for _ in texts]


@dataclass
class FakePoint:
    payload: dict[str, Any]
    score: float = 0.9


class FakeQdrant:
    def __init__(self, points: list[FakePoint]) -> None:
        self.points = points
        self.calls: list[dict[str, Any]] = []

    def search(
        self,
        collection: str,
        vector: list[float],
        payload_filter: dict[str, Any],
        limit: int,
    ) -> list[FakePoint]:
        self.calls.append(
            {
                "collection": collection,
                "vector": vector,
                "payload_filter": payload_filter,
                "limit": limit,
            }
        )
        return self.points


class FakeProductRepository:
    def __init__(
        self,
        candidate_ids: list[uuid.UUID] | None,
        products: dict[uuid.UUID, Any],
    ) -> None:
        self.candidate_ids = candidate_ids
        self.products = products
        self.filters_seen: ExtractedFilters | None = None

    async def get_distinct_values(
        self,
        tenant_id: uuid.UUID,
    ) -> tuple[frozenset[str], frozenset[str]]:
        return frozenset({"Cisco"}), frozenset({"switch"})

    async def find_by_filters(
        self,
        tenant_id: uuid.UUID,
        filters: ExtractedFilters,
    ) -> list[uuid.UUID] | None:
        self.filters_seen = filters
        return self.candidate_ids

    async def get_by_ids(
        self,
        tenant_id: uuid.UUID,
        product_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, Any]:
        return self.products


class FakeDocumentRepository:
    def __init__(self, documents: dict[uuid.UUID, Any] | None = None) -> None:
        self.documents = documents or {}
        self.find_by_type_calls: list[str] = []

    async def find_by_type(self, tenant_id: uuid.UUID, doc_type: str) -> list[uuid.UUID]:
        self.find_by_type_calls.append(doc_type)
        return list(self.documents)

    async def get_by_ids(
        self,
        tenant_id: uuid.UUID,
        document_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, Any]:
        return self.documents


def _settings() -> Any:
    return SimpleNamespace(
        embedding=EmbeddingSettings(model_name="BAAI/bge-m3"),
        rag=RagSettings(search_limit_default=5, search_limit_max=10),
        qdrant=QdrantSettings(url="http://qdrant", api_key="local"),
    )


def _session(
    tenant_id: uuid.UUID,
    *,
    product_interest: str = "Cisco switch",
    intent: str = "sales_inquiry",
) -> SessionContext:
    return SessionContext(
        tenant_id=tenant_id,
        session_id="s1",
        facts=FactsSchema(
            tenant_id=tenant_id,
            session_id="s1",
            product_interest=product_interest,
        ),
        conversation_state=ConversationStateSchema(
            tenant_id=tenant_id,
            session_id="s1",
            current_intent=intent,
        ),
    )


@pytest.mark.asyncio
async def test_retrieval_service_falls_back_to_unscoped_search_when_no_filters_match() -> None:
    tenant_id = uuid.uuid4()
    product_id = uuid.uuid4()
    product = SimpleNamespace(
        id=product_id,
        name="Cisco 48-port Switch",
        brand="Cisco",
        category="switch",
    )
    qdrant = FakeQdrant([FakePoint({"tenant_id": str(tenant_id), "product_id": str(product_id)})])
    service = RetrievalService(
        db_session=None,  # type: ignore[arg-type]
        settings=_settings(),
        product_repository=FakeProductRepository([], {product_id: product}),  # zero SQL candidates
        document_repository=FakeDocumentRepository(),
        filter_extractor=FilterExtractor(brands={"Cisco"}, categories={"switch"}),
        embedder=FakeEmbedder(),  # type: ignore[arg-type]
        qdrant=qdrant,  # type: ignore[arg-type]
    )

    result = await service.retrieve_products(_session(tenant_id), ExecutionContext())

    assert result.success is True
    assert result.product_ids == [product_id]
    must = qdrant.calls[0]["payload_filter"]["must"]
    assert must == [{"key": "tenant_id", "match": {"value": str(tenant_id)}}]


@pytest.mark.asyncio
async def test_retrieve_docs_reuses_product_ids_from_execution_context() -> None:
    tenant_id = uuid.uuid4()
    product_id = uuid.uuid4()
    document_id = uuid.uuid4()
    document = SimpleNamespace(
        id=document_id,
        title="Install Guide",
        document_type="installation_guide",
        product_id=product_id,
    )
    qdrant = FakeQdrant(
        [
            FakePoint(
                {
                    "tenant_id": str(tenant_id),
                    "document_id": str(document_id),
                    "product_id": str(product_id),
                    "chunk_text": "Install it carefully.",
                }
            )
        ]
    )
    context = ExecutionContext(
        retrieve_products=ToolExecutionResult(
            step="retrieve_products",
            success=True,
            result_summary="",
            product_ids=[product_id],
        )
    )
    doc_repo = FakeDocumentRepository({document_id: document})
    service = RetrievalService(
        db_session=None,  # type: ignore[arg-type]
        settings=_settings(),
        product_repository=FakeProductRepository(None, {}),
        document_repository=doc_repo,
        filter_extractor=FilterExtractor(),
        embedder=FakeEmbedder(),  # type: ignore[arg-type]
        qdrant=qdrant,  # type: ignore[arg-type]
    )

    result = await service.retrieve_docs(
        _session(tenant_id, intent="installation_guidance"),
        context,
    )

    assert result.success is True
    must = qdrant.calls[0]["payload_filter"]["must"]
    assert {"key": "product_id", "match": {"any": [str(product_id)]}} in must
    assert {"key": "document_type", "match": {"value": "installation_guide"}} in must
    assert doc_repo.find_by_type_calls == ["installation_guide"]
    assert json.loads(result.result_summary)[0]["document_id"] == str(document_id)


@pytest.mark.asyncio
async def test_retrieve_docs_scoped_to_tenant_when_no_product_ids_in_context() -> None:
    tenant_id = uuid.uuid4()
    qdrant = FakeQdrant([])
    service = RetrievalService(
        db_session=None,  # type: ignore[arg-type]
        settings=_settings(),
        product_repository=FakeProductRepository(None, {}),
        document_repository=FakeDocumentRepository(),
        filter_extractor=FilterExtractor(),
        embedder=FakeEmbedder(),  # type: ignore[arg-type]
        qdrant=qdrant,  # type: ignore[arg-type]
    )

    result = await service.retrieve_docs(
        _session(tenant_id, intent="pdf_documentation_search"),
        ExecutionContext(),
    )

    assert result.success is True
    assert qdrant.calls[0]["payload_filter"]["must"] == [
        {"key": "tenant_id", "match": {"value": str(tenant_id)}}
    ]


def test_bge_m3_embedder_produces_1024_dimensional_vectors() -> None:
    class FakeModel:
        def encode(self, texts: list[str]) -> list[list[float]]:
            return [[0.1] * BGE_M3_VECTOR_SIZE for _ in texts]

    vectors = BgeM3Embedder(model=FakeModel()).embed(["hello"])

    assert len(vectors) == 1
    assert len(vectors[0]) == BGE_M3_VECTOR_SIZE
