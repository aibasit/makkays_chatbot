"""Local ingestion service for product and document RAG data."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.rag.embeddings import BGE_M3_VECTOR_SIZE, BgeM3Embedder
from app.rag.qdrant_client import QdrantWrapper
from app.rag.repository import DocumentRepository, ProductRepository
from app.rag.retrieval_service import DOCUMENT_COLLECTION, PRODUCT_COLLECTION
from app.rag.schemas import DocumentIngestRecord, ProductIngestRecord


class IngestionService:
    """Batch-load product/document metadata and Qdrant vectors."""

    def __init__(
        self,
        db_session: AsyncSession,
        settings: Settings,
        *,
        embedder: BgeM3Embedder | None = None,
        qdrant: QdrantWrapper | None = None,
    ) -> None:
        self.settings = settings
        self.product_repository = ProductRepository(db_session)
        self.document_repository = DocumentRepository(db_session)
        self.embedder = embedder or BgeM3Embedder(settings.embedding.model_name)
        self.qdrant = qdrant or QdrantWrapper(settings)

    def ensure_collections(self) -> None:
        """Ensure product and document collections exist."""
        self.qdrant.ensure_collection(PRODUCT_COLLECTION, vector_size=BGE_M3_VECTOR_SIZE)
        self.qdrant.ensure_collection(DOCUMENT_COLLECTION, vector_size=BGE_M3_VECTOR_SIZE)

    async def ingest_products(self, source_path: str, tenant_id: UUID) -> int:
        """Ingest a JSON array of product records."""
        records = [
            ProductIngestRecord(**item)
            for item in json.loads(Path(source_path).read_text(encoding="utf-8"))
        ]
        if not records:
            return 0
        texts = [_product_text(record) for record in records]
        vectors = self.embedder.embed(texts)
        points = []
        for record, vector in zip(records, vectors, strict=True):
            product = await self.product_repository.create(
                tenant_id=tenant_id,
                name=record.name,
                brand=record.brand,
                category=record.category,
                description=record.description,
                specs=record.specs,
            )
            points.append(
                {
                    "id": str(product.id),
                    "vector": vector,
                    "payload": {
                        "tenant_id": str(tenant_id),
                        "product_id": str(product.id),
                        "name": product.name,
                        "brand": product.brand,
                        "category": product.category,
                    },
                }
            )
        self.qdrant.upsert(PRODUCT_COLLECTION, points)
        return len(records)

    async def ingest_documents(
        self,
        source_path: str,
        tenant_id: UUID,
        *,
        doc_type: str = "technical_doc",
    ) -> int:
        """Ingest document records from a JSON file or text/Markdown directory."""
        records = _load_document_records(source_path, doc_type)
        if not records:
            return 0
        vectors = self.embedder.embed([record.content for record in records])
        points = []
        for record, vector in zip(records, vectors, strict=True):
            document = await self.document_repository.create(
                tenant_id=tenant_id,
                title=record.title,
                source_path=record.source_path,
                document_type=record.document_type,
                product_id=record.product_id,
            )
            points.append(
                {
                    "id": str(document.id),
                    "vector": vector,
                    "payload": {
                        "tenant_id": str(tenant_id),
                        "document_id": str(document.id),
                        "product_id": str(document.product_id) if document.product_id else None,
                        "title": document.title,
                        "document_type": document.document_type,
                        "chunk_text": record.content,
                    },
                }
            )
        self.qdrant.upsert(DOCUMENT_COLLECTION, points)
        return len(records)


def _product_text(record: ProductIngestRecord) -> str:
    spec_text = " ".join(
        f"{item.get('key') or item.get('spec_key')}: {item.get('value') or item.get('spec_value')}"
        for item in record.specs
    )
    parts = [
        record.name,
        record.brand or "",
        record.category or "",
        record.description or "",
        spec_text,
    ]
    return " ".join(item for item in parts if item)


def _load_document_records(source_path: str, doc_type: str) -> list[DocumentIngestRecord]:
    path = Path(source_path)
    if path.is_file() and path.suffix.lower() == ".json":
        return [
            DocumentIngestRecord(**{"document_type": doc_type, **item})
            for item in json.loads(path.read_text(encoding="utf-8"))
        ]
    if path.is_file():
        return [
            DocumentIngestRecord(
                title=path.stem,
                content=path.read_text(encoding="utf-8"),
                source_path=str(path),
                document_type=doc_type,
            )
        ]
    records: list[DocumentIngestRecord] = []
    for candidate in sorted(path.rglob("*")):
        if candidate.suffix.lower() not in {".md", ".txt"}:
            continue
        records.append(
            DocumentIngestRecord(
                title=candidate.stem,
                content=candidate.read_text(encoding="utf-8"),
                source_path=str(candidate),
                document_type=doc_type,
            )
        )
    return records
