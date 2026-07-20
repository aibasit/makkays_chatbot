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


ConstraintOperator = Literal["eq", "gte", "lte", "between", "in", "not_eq", "nearest"]


class Constraint(BaseModel):
    """One deterministic, category-scoped numeric constraint.

    Replaces the old single `capacity_requirement`/`capacity_unit` pair for
    unit-specific fields (capacity_kva, power_factor, current_a, ...) — a
    generic capacity filter can't safely tell kVA, A, Ah, and kWh apart, so
    each field carries its own unit and its own comparison semantics.
    `nearest` is not a SQL `WHERE` clause — it's a ranking instruction
    (`ORDER BY ABS(column - value)`), handled specially in
    `ProductRepository.find_by_filters`/`list_products` rather than as a
    boolean condition like the other operators.
    """

    field: str
    operator: ConstraintOperator
    # Single comparison value for eq/gte/lte/not_eq/nearest.
    value: Decimal | str | None = None
    # Upper bound, only meaningful for operator == "between" (`value` is the lower bound).
    value_max: Decimal | None = None
    # Candidate set, only meaningful for operator == "in".
    values: list[Decimal | str] | None = None
    unit: str | None = None
    hard: bool = True
    source_text: str | None = None


class ExtractedFilters(BaseModel):
    """Structured filters extracted deterministically from a retrieval query."""

    brand: str | None = None
    category: str | None = None
    spec_filters: dict[str, str] = Field(default_factory=dict)
    doc_type: str | None = None
    use_case: str | None = None
    # A client-stated power/capacity requirement (e.g. "5kVA"), parsed by
    # app.rag.capacity.parse_capacity_requirement. min_value == max_value for a
    # single stated figure; capacity_unit is "KVA" or "A". Kept alongside
    # `constraints` below (not replaced) — existing callers (e.g.
    # `BOMService`) still build `ExtractedFilters` directly with this pair,
    # and it remains the fallback for categories with no typed column yet.
    capacity_requirement: Decimal | None = None
    capacity_unit: str | None = None
    # Category-aware, unit-specific, operator-bearing constraints (see
    # `Constraint`) — additive to the fields above, not a replacement for them.
    constraints: list[Constraint] = Field(default_factory=list)
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
            or self.constraints
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
