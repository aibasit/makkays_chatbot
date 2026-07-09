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
        *,
        specs: dict[uuid.UUID, list[Any]] | None = None,
        list_products_result: list[Any] | None = None,
    ) -> None:
        self.candidate_ids = candidate_ids
        self.products = products
        self.specs = specs or {}
        self.list_products_result = list_products_result or []
        self.filters_seen: ExtractedFilters | None = None
        self.list_products_calls: list[dict[str, Any]] = []

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

    async def get_specs_for_products(
        self,
        product_ids: list[uuid.UUID],
        tenant_id: uuid.UUID,
    ) -> dict[uuid.UUID, list[Any]]:
        return {pid: self.specs[pid] for pid in product_ids if pid in self.specs}

    async def list_products(
        self,
        tenant_id: uuid.UUID,
        *,
        category: str | None = None,
        brand: str | None = None,
        limit: int,
    ) -> list[Any]:
        self.list_products_calls.append({"category": category, "brand": brand, "limit": limit})
        return self.list_products_result


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
    message: str = "",
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
        message=message,
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


@pytest.mark.asyncio
async def test_retrieve_products_list_all_bypasses_qdrant() -> None:
    """"List all your UPS options" must not be silently truncated by vector top-K."""
    tenant_id = uuid.uuid4()
    product_ids = [uuid.uuid4() for _ in range(12)]
    listed_products = [
        SimpleNamespace(id=pid, name=f"UPS Model {i}", brand="Makkays", category="UPS Solutions")
        for i, pid in enumerate(product_ids)
    ]
    qdrant = FakeQdrant([FakePoint({"tenant_id": str(tenant_id), "product_id": str(uuid.uuid4())})])
    product_repository = FakeProductRepository(None, {}, list_products_result=listed_products)
    service = RetrievalService(
        db_session=None,  # type: ignore[arg-type]
        settings=_settings(),
        product_repository=product_repository,
        document_repository=FakeDocumentRepository(),
        filter_extractor=FilterExtractor(categories={"ups"}),
        embedder=FakeEmbedder(),  # type: ignore[arg-type]
        qdrant=qdrant,  # type: ignore[arg-type]
    )

    result = await service.retrieve_products(
        _session(tenant_id, message="list all your UPS options"),
        ExecutionContext(),
    )

    assert result.success is True
    assert len(result.product_ids) == 12
    assert qdrant.calls == []  # Qdrant never touched for a list-all request
    assert product_repository.list_products_calls[0]["category"] == "ups"


@pytest.mark.asyncio
async def test_retrieve_products_attaches_full_specs_to_results() -> None:
    """The respond step needs real spec data to ground a recommendation in —
    not just name/brand/category, which is all it used to get."""
    tenant_id = uuid.uuid4()
    product_id = uuid.uuid4()
    product = SimpleNamespace(id=product_id, name="T-4111 UPS", brand="Makkays", category="UPS Solutions")
    spec = SimpleNamespace(spec_key="capacity_range", spec_value="1-10kVA")
    qdrant = FakeQdrant([FakePoint({"tenant_id": str(tenant_id), "product_id": str(product_id)})])
    service = RetrievalService(
        db_session=None,  # type: ignore[arg-type]
        settings=_settings(),
        product_repository=FakeProductRepository(
            [product_id], {product_id: product}, specs={product_id: [spec]}
        ),
        document_repository=FakeDocumentRepository(),
        filter_extractor=FilterExtractor(brands={"Makkays"}, categories={"switch"}),
        embedder=FakeEmbedder(),  # type: ignore[arg-type]
        qdrant=qdrant,  # type: ignore[arg-type]
    )

    result = await service.retrieve_products(_session(tenant_id), ExecutionContext())

    parsed = json.loads(result.result_summary)
    assert parsed[0]["specs"] == [{"key": "capacity_range", "value": "1-10kVA"}]


def test_bge_m3_embedder_produces_1024_dimensional_vectors() -> None:
    class FakeModel:
        def encode(self, texts: list[str]) -> list[list[float]]:
            return [[0.1] * BGE_M3_VECTOR_SIZE for _ in texts]

    vectors = BgeM3Embedder(model=FakeModel()).embed(["hello"])

    assert len(vectors) == 1
    assert len(vectors[0]) == BGE_M3_VECTOR_SIZE
