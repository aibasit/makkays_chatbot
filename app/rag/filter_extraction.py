"""Deterministic structured filter extraction for RAG queries."""

from __future__ import annotations

import re
from uuid import UUID

from app.logging_config import get_logger
from app.rag.repository import ProductRepository
from app.rag.schemas import ExtractedFilters

logger = get_logger(__name__)

_PORT_COUNT_PATTERN = re.compile(r"\b(\d+)\s*(?:-| )?ports?\b", re.IGNORECASE)
_POE_PATTERN = re.compile(r"\bpoe\+?\b", re.IGNORECASE)
_UPS_PATTERN = re.compile(r"\bups\b", re.IGNORECASE)

_USE_CASES: tuple[str, ...] = (
    "school",
    "hospital",
    "office",
    "data center",
    "datacenter",
    "cctv",
    "enterprise",
    "smb",
)

INTENT_DOC_TYPE_MAP: dict[str, str] = {
    "installation_guidance": "installation_guide",
    "warranty_information": "warranty_doc",
    "troubleshooting": "manual",
    "technical_support": "technical_doc",
}


class FilterExtractor:
    """Extract brand/category/spec/doc filters without using the LLM."""

    def __init__(
        self,
        product_repository: ProductRepository | None = None,
        *,
        brands: set[str] | frozenset[str] | None = None,
        categories: set[str] | frozenset[str] | None = None,
    ) -> None:
        self.product_repository = product_repository
        self._static_brands = frozenset(brands or [])
        self._static_categories = frozenset(categories or [])
        self._vocabulary_cache: dict[UUID, tuple[frozenset[str], frozenset[str]]] = {}

    async def extract(
        self,
        query: str,
        tenant_id: UUID,
        *,
        intent: str | None = None,
    ) -> ExtractedFilters:
        """Return deterministic filters extracted from query and intent context."""
        brands, categories = await self._vocabulary(tenant_id)
        lowered = query.lower()
        spec_filters: dict[str, str] = {}

        port_match = _PORT_COUNT_PATTERN.search(query)
        if port_match:
            spec_filters["port_count"] = port_match.group(1)
        if _POE_PATTERN.search(query):
            spec_filters["poe"] = "true"
        if _UPS_PATTERN.search(query):
            spec_filters["category_hint"] = "ups"

        use_case = _first_literal_match(lowered, _USE_CASES)
        doc_type = INTENT_DOC_TYPE_MAP.get(intent or "")

        filters = ExtractedFilters(
            brand=_first_vocabulary_match(query, brands),
            category=_first_vocabulary_match(query, categories),
            spec_filters=spec_filters,
            doc_type=doc_type,
            use_case=use_case,
        )
        logger.debug(
            "rag_filters_extracted",
            extra={
                "tenant_id": str(tenant_id),
                "brand": filters.brand,
                "category": filters.category,
                "spec_filters": filters.spec_filters,
                "doc_type": filters.doc_type,
                "use_case": filters.use_case,
            },
        )
        return filters

    async def _vocabulary(self, tenant_id: UUID) -> tuple[frozenset[str], frozenset[str]]:
        if self.product_repository is None:
            return self._static_brands, self._static_categories
        cached = self._vocabulary_cache.get(tenant_id)
        if cached is not None:
            return cached
        brands, categories = await self.product_repository.get_distinct_values(tenant_id)
        if self._static_brands:
            brands = brands | self._static_brands
        if self._static_categories:
            categories = categories | self._static_categories
        self._vocabulary_cache[tenant_id] = (brands, categories)
        return brands, categories


def _first_vocabulary_match(query: str, vocabulary: frozenset[str]) -> str | None:
    matches: list[tuple[int, str]] = []
    for value in vocabulary:
        pattern = re.compile(rf"(?<!\w){re.escape(value)}(?!\w)", re.IGNORECASE)
        match = pattern.search(query)
        if match:
            matches.append((match.start(), value))
    if not matches:
        return None
    matches.sort(key=lambda item: item[0])
    return matches[0][1]


def _first_literal_match(lowered_query: str, values: tuple[str, ...]) -> str | None:
    matches = [(lowered_query.find(value), value) for value in values if value in lowered_query]
    matches = [item for item in matches if item[0] >= 0]
    if not matches:
        return None
    matches.sort(key=lambda item: item[0])
    value = matches[0][1]
    return "data_center" if value in {"data center", "datacenter"} else value
