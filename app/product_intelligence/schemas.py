"""Pydantic schemas for product intelligence results."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.rag.schemas import ProductResult

# Allowed compatibility_type values (Module 00 v4.2 taxonomy scope).
COMPATIBILITY_TYPES: frozenset[str] = frozenset({"ups", "battery", "controller", "sfp", "rack"})


class ComparisonResult(BaseModel):
    """Structured comparison of two or more products plus an LLM narration."""

    products: list[ProductResult]
    comparison_table: dict[str, dict[str, str | None]]
    ai_summary: str


class CompatibilityResult(BaseModel):
    """Outcome of a compatibility check between two products."""

    primary_product_id: UUID
    secondary_product_id: UUID
    compatibility_type: str
    is_compatible: bool | None
    source: Literal["rule", "llm_inference"]
    notes: str | None = None


class AccessoryResult(BaseModel):
    """One recommended accessory for a primary product."""

    product_id: UUID
    name: str
    relation_type: str
    source: Literal["explicit", "vector_similarity"]
