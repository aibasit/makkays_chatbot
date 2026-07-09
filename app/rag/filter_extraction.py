"""Deterministic structured filter extraction for RAG queries."""

from __future__ import annotations

import re
from uuid import UUID

from app.logging_config import get_logger
from app.rag.capacity import parse_capacity_requirement
from app.rag.repository import ProductRepository
from app.rag.schemas import ExtractedFilters

logger = get_logger(__name__)

_PORT_COUNT_PATTERN = re.compile(r"\b(\d+)\s*(?:-| )?ports?\b", re.IGNORECASE)
_POE_PATTERN = re.compile(r"\bpoe\+?\b", re.IGNORECASE)
_UPS_PATTERN = re.compile(r"\bups\b", re.IGNORECASE)

# "list all your UPS options", "show me every product", "what models do you have",
# "full range/list/catalog" — an exhaustive listing request rather than a
# best-match search. See RetrievalService.retrieve_products.
_LIST_ALL_PATTERN = re.compile(
    r"\b(?:all|every|entire|full|complete)\b[^.?!]{0,30}\b(?:products?|options?|models?|"
    r"range|lineup|list|catalog|types?)\b"
    r"|\blist\s+(?:all|every)\b"
    r"|\bwhat\s+(?:products?|options?|models?)\s+do\s+you\s+(?:have|offer|carry|sell)\b",
    re.IGNORECASE,
)

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
        raw_message: str | None = None,
    ) -> ExtractedFilters:
        """Return deterministic filters extracted from query and intent context.

        `raw_message` (the current turn's literal text, when available) is
        combined with `query` for every deterministic check below — `query` alone
        may be a reconstructed fact like "UPS system" rather than the client's
        actual wording, and a stated figure like "5kVA" only ever appears in the
        literal message.
        """
        combined_text = f"{query} {raw_message}" if raw_message else query
        brands, categories = await self._vocabulary(tenant_id)
        lowered = combined_text.lower()
        spec_filters: dict[str, str] = {}

        port_match = _PORT_COUNT_PATTERN.search(combined_text)
        if port_match:
            spec_filters["port_count"] = port_match.group(1)
        if _POE_PATTERN.search(combined_text):
            spec_filters["poe"] = "true"

        category = _first_vocabulary_match(combined_text, categories)
        if category is None and _UPS_PATTERN.search(combined_text):
            # The catalog's category is the full "UPS Solutions", which a plain
            # substring match against a bare "UPS" mention won't find — resolve
            # it directly instead of the previous approach (a "category_hint"
            # spec_filters entry with no corresponding product_spec row, which
            # made every UPS-mentioning query silently narrow to zero SQL
            # candidates and fall back to fully unscoped semantic search).
            category = _first_category_containing(categories, "ups")

        use_case = _first_literal_match(lowered, _USE_CASES)
        doc_type = INTENT_DOC_TYPE_MAP.get(intent or "")
        capacity = parse_capacity_requirement(combined_text)
        list_all = bool(_LIST_ALL_PATTERN.search(combined_text))

        filters = ExtractedFilters(
            brand=_first_vocabulary_match(combined_text, brands),
            category=category,
            spec_filters=spec_filters,
            doc_type=doc_type,
            use_case=use_case,
            capacity_requirement=capacity.min_value if capacity else None,
            capacity_unit=capacity.unit if capacity else None,
            list_all=list_all,
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
                "capacity_requirement": str(filters.capacity_requirement) if filters.capacity_requirement else None,
                "capacity_unit": filters.capacity_unit,
                "list_all": filters.list_all,
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


def _first_category_containing(categories: frozenset[str], substring: str) -> str | None:
    matches = sorted(value for value in categories if substring.lower() in value.lower())
    return matches[0] if matches else None


def _first_literal_match(lowered_query: str, values: tuple[str, ...]) -> str | None:
    matches = [(lowered_query.find(value), value) for value in values if value in lowered_query]
    matches = [item for item in matches if item[0] >= 0]
    if not matches:
        return None
    matches.sort(key=lambda item: item[0])
    value = matches[0][1]
    return "data_center" if value in {"data center", "datacenter"} else value
