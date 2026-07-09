"""Pydantic schemas for RAG filtering, results, and ingestion."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


DocumentType = Literal[
    "datasheet",
    "manual",
    "brochure",
    "installation_guide",
    "technical_doc",
    "warranty_doc",
]


class ExtractedFilters(BaseModel):
    """Structured filters extracted deterministically from a retrieval query."""

    brand: str | None = None
    category: str | None = None
    spec_filters: dict[str, str] = Field(default_factory=dict)
    doc_type: str | None = None
    use_case: str | None = None
    # A client-stated power/capacity requirement (e.g. "5kVA"), parsed by
    # app.rag.capacity.parse_capacity_requirement. min_value == max_value for a
    # single stated figure; capacity_unit is "KVA" or "A".
    capacity_requirement: Decimal | None = None
    capacity_unit: str | None = None
    # Whether the message asks for an exhaustive category/brand listing
    # ("list all your UPS options") rather than a best-match search — see
    # RetrievalService.retrieve_products and ProductRepository.list_products.
    list_all: bool = False

    def has_product_filters(self) -> bool:
        """Return whether the filters should trigger SQL product narrowing."""
        return bool(
            self.brand
            or self.category
            or self.spec_filters
            or self.use_case
            or self.capacity_requirement is not None
        )


class ProductResult(BaseModel):
    """One product returned from layered retrieval."""

    product_id: UUID
    name: str
    brand: str | None = None
    category: str | None = None
    score: float
    # Full spec key/value pairs (capacity_range, subcategory, model codes, ...),
    # so the response LLM can ground a comparison/recommendation in real data
    # instead of inferring numbers from the product name string.
    specs: list[dict[str, str]] = Field(default_factory=list)


class DocResult(BaseModel):
    """One document chunk returned from layered retrieval."""

    document_id: UUID
    title: str
    chunk_text: str
    score: float
    document_type: str | None = None
    product_id: UUID | None = None


class ProductIngestRecord(BaseModel):
    """Input record for product ingestion."""

    name: str
    brand: str | None = None
    category: str | None = None
    description: str | None = None
    specs: list[dict[str, Any]] = Field(default_factory=list)
    documents: list[dict[str, Any]] = Field(default_factory=list)


class DocumentIngestRecord(BaseModel):
    """Input record for document ingestion."""

    title: str
    content: str
    source_path: str
    document_type: str = "technical_doc"
    product_id: UUID | None = None
