"""Layered RAG retrieval service and Module 10 tool entrypoints."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.engine import get_sessionmaker
from app.dependencies import get_settings
from app.logging_config import get_logger
from app.observability import registry as metrics
from app.rag.embeddings import BgeM3Embedder
from app.rag.exceptions import RagQueryError
from app.rag.filter_extraction import FilterExtractor
from app.rag.qdrant_client import QdrantWrapper
from app.rag.repository import DocumentRepository, ProductRepository
from app.rag.schemas import Constraint, DocResult, ExtractedFilters, ProductResult
from app.tools.schemas import ExecutionContext, SessionContext, ToolExecutionResult

logger = get_logger(__name__)

PRODUCT_COLLECTION = "products_v1"
DOCUMENT_COLLECTION = "documents_v1"

# Lowest-priority first — `_relax_and_retry` drops constraints in this order
# when the full constraint set matches zero products, so the *most* specific,
# defining requirements (capacity, series, voltage/current) survive longest
# and only genuinely secondary preferences (sub-category, battery mode, form
# factor, ...) are relaxed first. See `RetrievalService._relax_and_retry`.
_RELAXATION_PRIORITY: tuple[str, ...] = (
    "service_life_type", "sub_category_key", "product_type_key",
    "battery_mode", "form_factor_key", "chemistry_key", "technology_key",
    "parallel_capable", "max_parallel_units", "service_life_years",
    "power_factor", "voltage_class_v", "max_discharge_power_kw",
    "phase_input_count", "phase_output_count",
    "current_a", "capacity_ah", "energy_kwh", "nominal_voltage_vdc",
    "series_key", "capacity_kva",
)
_FIELD_LABELS: dict[str, str] = {
    "capacity_kva": "capacity (kVA)",
    "power_factor": "power factor",
    "current_a": "current rating",
    "phase_input_count": "input phase",
    "phase_output_count": "output phase",
    "form_factor_key": "form factor",
    "battery_mode": "battery configuration",
    "parallel_capable": "parallel capability",
    "technology_key": "technology",
    "voltage_class_v": "voltage class",
    "nominal_voltage_vdc": "voltage",
    "capacity_ah": "capacity (Ah)",
    "energy_kwh": "energy (kWh)",
    "chemistry_key": "chemistry",
    "series_key": "series",
    "max_discharge_power_kw": "max discharge power",
    "max_parallel_units": "max parallel units",
    "service_life_years": "service life",
}


class RetrievalService:
    """Composes filter extraction, SQL narrowing, embeddings, and Qdrant search."""

    def __init__(
        self,
        db_session: AsyncSession,
        settings: Settings,
        *,
        product_repository: ProductRepository | None = None,
        document_repository: DocumentRepository | None = None,
        filter_extractor: FilterExtractor | None = None,
        embedder: BgeM3Embedder | None = None,
        qdrant: QdrantWrapper | None = None,
    ) -> None:
        self.settings = settings
        self.product_repository = product_repository or ProductRepository(db_session)
        self.document_repository = document_repository or DocumentRepository(db_session)
        self.filter_extractor = filter_extractor or FilterExtractor(self.product_repository)
        self.embedder = embedder or BgeM3Embedder(settings.embedding.model_name)
        self.qdrant = qdrant or QdrantWrapper(settings)

    async def retrieve_products(
        self,
        session: SessionContext,
        context: ExecutionContext,
    ) -> ToolExecutionResult:
        """Retrieve product candidates for the active session context."""
        query = _query_from_session(session)
        filters = await self.filter_extractor.extract(
            query,
            session.tenant_id,
            intent=session.conversation_state.current_intent,
            raw_message=session.message,
        )

        if filters.list_all:
            # An exhaustive listing request — top-K vector search would silently
            # truncate a large category, so bypass Qdrant entirely. Constraints
            # are still applied here (not just category/brand) — "list all
            # tower UPS" must list all tower UPS, not the entire UPS category;
            # the two SQL paths share `_build_conditions` in the repository so
            # they can't silently drift apart on what "matches" means.
            products = await self.product_repository.list_products(
                session.tenant_id,
                category=filters.category,
                brand=filters.brand,
                constraints=filters.constraints,
                limit=self._list_all_limit(),
            )
            results = await self._map_products_direct(session.tenant_id, products)
            logger.debug(
                "rag_products_listed",
                extra={
                    "tenant_id": str(session.tenant_id),
                    "category": filters.category,
                    "brand": filters.brand,
                    "result_count": len(results),
                },
            )
            metrics.metrics_registry.increment_rag_hit(hit=bool(results))
            return ToolExecutionResult(
                step="retrieve_products",
                success=True,
                result_summary=json.dumps(
                    [result.model_dump(mode="json") for result in results],
                    separators=(",", ":"),
                ),
                product_ids=[result.product_id for result in results],
            )

        candidate_ids = await self.product_repository.find_by_filters(session.tenant_id, filters)
        relaxation_notice: str | None = None
        if candidate_ids is not None and not candidate_ids and filters.constraints:
            # The hard constraint set matched real product filters but zero
            # rows — never silently fall back to a fully unscoped search here
            # (see `_product_qdrant_filter`'s empty-list handling below);
            # relax one requirement at a time instead so the client is told
            # specifically what couldn't be matched exactly.
            candidate_ids, dropped = await self._relax_and_retry(session.tenant_id, filters)
            if dropped is not None:
                label = _FIELD_LABELS.get(dropped.field, dropped.field)
                detail = f" ({dropped.source_text})" if dropped.source_text else ""
                relaxation_notice = (
                    f"No exact match for the requested {label}{detail} — showing the "
                    "closest available alternatives instead of an exact match. Say so "
                    "plainly rather than presenting these as an exact match."
                )
        vector = await self._embed_query(query)
        payload_filter = _product_qdrant_filter(session.tenant_id, candidate_ids)
        points = self.qdrant.search(
            self.product_collection,
            vector,
            payload_filter,
            self._bounded_limit(),
        )
        results = await self._map_product_points(session.tenant_id, points)
        logger.debug(
            "rag_products_retrieved",
            extra={
                "tenant_id": str(session.tenant_id),
                "candidate_count": None if candidate_ids is None else len(candidate_ids),
                "result_count": len(results),
                "relaxed": relaxation_notice is not None,
            },
        )
        metrics.metrics_registry.increment_rag_hit(hit=bool(results))
        result_dicts: list[dict[str, Any]] = [result.model_dump(mode="json") for result in results]
        if relaxation_notice:
            # A plain dict, not a `ProductResult` — `_retrieved_sources` in
            # `app.tools.executor` flattens any dict in this JSON list into the
            # `respond`/`explain_specification` LLM context as-is, the same
            # channel already used for the "no real match, don't invent one"
            # notice, so this reaches the final answer with no further wiring.
            result_dicts.append({"notice": relaxation_notice})
        return ToolExecutionResult(
            step="retrieve_products",
            success=True,
            result_summary=json.dumps(result_dicts, separators=(",", ":")),
            product_ids=[result.product_id for result in results],
        )

    async def _relax_and_retry(
        self, tenant_id: UUID, filters: ExtractedFilters
    ) -> tuple[list[UUID] | None, Constraint | None]:
        """Drop the lowest-priority constraint at a time until results appear.

        Never drops every constraint at once — relaxes one requirement, re-runs,
        and stops at the first removal that produces results, so the caller can
        report specifically which requirement couldn't be matched exactly
        rather than silently blending "hard filters found nothing" into an
        unscoped search. See `_RELAXATION_PRIORITY`.
        """
        remaining = list(filters.constraints)
        dropped: Constraint | None = None
        while remaining:
            remaining.sort(
                key=lambda c: _RELAXATION_PRIORITY.index(c.field) if c.field in _RELAXATION_PRIORITY else -1
            )
            dropped = remaining.pop(0)
            relaxed_filters = filters.model_copy(update={"constraints": list(remaining)})
            candidate_ids = await self.product_repository.find_by_filters(tenant_id, relaxed_filters)
            if candidate_ids:
                return candidate_ids, dropped
        return None, dropped

    async def retrieve_docs(
        self,
        session: SessionContext,
        context: ExecutionContext,
    ) -> ToolExecutionResult:
        """Retrieve documents, reusing product IDs from prior product retrieval when available."""
        filters = await self.filter_extractor.extract(
            _query_from_session(session),
            session.tenant_id,
            intent=session.conversation_state.current_intent,
        )
        return await self.retrieve_docs_by_type(session, context, doc_type=filters.doc_type)

    async def retrieve_docs_by_type(
        self,
        session: SessionContext,
        context: ExecutionContext,
        doc_type: str | None = None,
    ) -> ToolExecutionResult:
        """Retrieve documents with optional document-type scoping."""
        query = _query_from_session(session)
        product_ids = context.get_product_ids()
        if product_ids is None:
            logger.debug(
                "retrieve_docs_unscoped",
                extra={"tenant_id": str(session.tenant_id), "reason": "no product_ids"},
            )
        candidate_doc_ids: list[UUID] | None = None
        if doc_type is not None:
            candidate_doc_ids = await self.document_repository.find_by_type(
                session.tenant_id,
                doc_type,
            )
        vector = await self._embed_query(query)
        payload_filter = _document_qdrant_filter(
            session.tenant_id,
            product_ids=product_ids,
            document_ids=candidate_doc_ids,
            doc_type=doc_type,
        )
        points = self.qdrant.search(
            self.document_collection,
            vector,
            payload_filter,
            self._bounded_limit(),
        )
        results = await self._map_document_points(session.tenant_id, points)
        metrics.metrics_registry.increment_rag_hit(hit=bool(results))
        return ToolExecutionResult(
            step="retrieve_docs",
            success=True,
            result_summary=json.dumps(
                [result.model_dump(mode="json") for result in results],
                separators=(",", ":"),
            ),
        )

    @property
    def product_collection(self) -> str:
        return getattr(self.settings.rag, "qdrant_collection_products", PRODUCT_COLLECTION)

    @property
    def document_collection(self) -> str:
        return getattr(self.settings.rag, "qdrant_collection_documents", DOCUMENT_COLLECTION)

    async def _embed_query(self, query: str) -> list[float]:
        loop = asyncio.get_running_loop()
        vectors = await loop.run_in_executor(None, self.embedder.embed, [query])
        return vectors[0]

    def _bounded_limit(self) -> int:
        return max(
            1,
            min(self.settings.rag.search_limit_default, self.settings.rag.search_limit_max),
        )

    def _list_all_limit(self) -> int:
        return max(1, self.settings.rag.list_all_limit)

    async def _map_product_points(self, tenant_id: UUID, points: list[Any]) -> list[ProductResult]:
        payloads = [_point_payload(point) for point in points]
        ids = [_uuid_from_payload(payload, "product_id") for payload in payloads]
        ids = [item for item in ids if item is not None]
        products = await self.product_repository.get_by_ids(tenant_id, ids)
        specs_by_product = await self.product_repository.get_specs_for_products(ids, tenant_id)
        results: list[ProductResult] = []
        for point, payload in zip(points, payloads, strict=False):
            product_id = _uuid_from_payload(payload, "product_id")
            if product_id is None:
                continue
            product = products.get(product_id)
            results.append(
                ProductResult(
                    product_id=product_id,
                    name=(product.name if product else str(payload.get("name") or product_id)),
                    brand=(product.brand if product else payload.get("brand")),
                    category=(product.category if product else payload.get("category")),
                    score=float(getattr(point, "score", payload.get("score", 0.0)) or 0.0),
                    specs=_specs_to_dicts(specs_by_product.get(product_id, [])),
                )
            )
        return results

    async def _map_products_direct(self, tenant_id: UUID, products: list[Any]) -> list[ProductResult]:
        """Build ProductResults straight from SQL rows, for the list-all path (no Qdrant)."""
        ids = [product.id for product in products]
        specs_by_product = await self.product_repository.get_specs_for_products(ids, tenant_id)
        return [
            ProductResult(
                product_id=product.id,
                name=product.name,
                brand=product.brand,
                category=product.category,
                score=1.0,
                specs=_specs_to_dicts(specs_by_product.get(product.id, [])),
            )
            for product in products
        ]

    async def _map_document_points(self, tenant_id: UUID, points: list[Any]) -> list[DocResult]:
        payloads = [_point_payload(point) for point in points]
        ids = [_uuid_from_payload(payload, "document_id") for payload in payloads]
        ids = [item for item in ids if item is not None]
        documents = await self.document_repository.get_by_ids(tenant_id, ids)
        results: list[DocResult] = []
        for point, payload in zip(points, payloads, strict=False):
            document_id = _uuid_from_payload(payload, "document_id")
            if document_id is None:
                continue
            document = documents.get(document_id)
            product_id = _uuid_from_payload(payload, "product_id")
            results.append(
                DocResult(
                    document_id=document_id,
                    title=(
                        document.title
                        if document
                        else str(payload.get("title") or document_id)
                    ),
                    chunk_text=str(payload.get("chunk_text") or payload.get("text") or ""),
                    score=float(getattr(point, "score", payload.get("score", 0.0)) or 0.0),
                    document_type=(
                        document.document_type if document else payload.get("document_type")
                    ),
                    product_id=product_id,
                )
            )
        return results


async def retrieve_products_tool(
    session: SessionContext,
    context: ExecutionContext,
) -> ToolExecutionResult:
    """Module 10 tool entrypoint for product retrieval."""
    settings = get_settings()
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db_session:
        service = RetrievalService(db_session, settings)
        return await service.retrieve_products(session, context)


async def retrieve_docs_tool(
    session: SessionContext,
    context: ExecutionContext,
) -> ToolExecutionResult:
    """Module 10 tool entrypoint for document retrieval."""
    settings = get_settings()
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db_session:
        service = RetrievalService(db_session, settings)
        return await service.retrieve_docs(session, context)


def _query_from_session(session: SessionContext) -> str:
    # Falls back to the raw current message when neither fact is set — found
    # live: an exact model-code question ("What are the technology, capacity,
    # phase, and voltage class of AVR model T300140240S?") sometimes isn't
    # extracted into `product_interest` by the LLM facts extractor, which used
    # to make this raise and skip retrieval entirely even though the message
    # itself carries everything the model-code filter needs.
    query = session.facts.product_interest or session.conversation_state.last_question or session.message
    if query is None or not query.strip():
        raise RagQueryError("RAG retrieval requires product_interest, last_question, or a message")
    return query.strip()


def _specs_to_dicts(specs: list[Any]) -> list[dict[str, str]]:
    return [{"key": spec.spec_key, "value": spec.spec_value} for spec in specs]


def _product_qdrant_filter(tenant_id: UUID, product_ids: list[UUID] | None) -> dict[str, Any]:
    must: list[dict[str, Any]] = [{"key": "tenant_id", "match": {"value": str(tenant_id)}}]
    if product_ids:
        must.append({"key": "product_id", "match": {"any": [str(item) for item in product_ids]}})
    return {"must": must}


def _document_qdrant_filter(
    tenant_id: UUID,
    *,
    product_ids: list[UUID] | None,
    document_ids: list[UUID] | None,
    doc_type: str | None,
) -> dict[str, Any]:
    must: list[dict[str, Any]] = [{"key": "tenant_id", "match": {"value": str(tenant_id)}}]
    if product_ids:
        must.append({"key": "product_id", "match": {"any": [str(item) for item in product_ids]}})
    if document_ids:
        must.append({"key": "document_id", "match": {"any": [str(item) for item in document_ids]}})
    if doc_type:
        must.append({"key": "document_type", "match": {"value": doc_type}})
    return {"must": must}


def _point_payload(point: Any) -> dict[str, Any]:
    payload = getattr(point, "payload", None)
    if payload is None and isinstance(point, dict):
        payload = point.get("payload")
    return dict(payload or {})


def _uuid_from_payload(payload: dict[str, Any], key: str) -> UUID | None:
    value = payload.get(key)
    if value in {None, ""}:
        return None
    return value if isinstance(value, UUID) else UUID(str(value))
