"""Unit tests for Module 11 deterministic filter extraction."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.rag.filter_extraction import FilterExtractor


@pytest.mark.asyncio
async def test_filter_extraction_finds_brand_category_and_port_count() -> None:
    extractor = FilterExtractor(brands={"Cisco", "Makkays"}, categories={"switch", "ups"})

    filters = await extractor.extract(
        "Need a 48-port Cisco switch for CCTV",
        uuid.uuid4(),
        intent="sales_inquiry",
    )

    assert filters.brand == "Cisco"
    assert filters.category == "switch"
    assert filters.spec_filters["port_count"] == "48"
    assert filters.use_case == "cctv"


@pytest.mark.asyncio
async def test_filter_extraction_returns_empty_when_no_match() -> None:
    extractor = FilterExtractor(brands={"Cisco"}, categories={"switch"})

    filters = await extractor.extract("Need something reliable", uuid.uuid4())

    assert filters.brand is None
    assert filters.category is None
    assert filters.spec_filters == {}
    assert filters.doc_type is None


@pytest.mark.asyncio
async def test_filter_extraction_conflict_uses_first_match() -> None:
    extractor = FilterExtractor(brands={"Cisco", "Makkays"}, categories={"switch"})

    filters = await extractor.extract("Compare Makkays and Cisco switch options", uuid.uuid4())

    assert filters.brand == "Makkays"


@pytest.mark.asyncio
async def test_filter_extraction_maps_intent_to_doc_type() -> None:
    extractor = FilterExtractor()

    filters = await extractor.extract(
        "How do I install this?",
        uuid.uuid4(),
        intent="installation_guidance",
    )

    assert filters.doc_type == "installation_guide"


@pytest.mark.asyncio
async def test_filter_extraction_bare_ups_mention_resolves_to_full_category_name() -> None:
    """Regression test for a real bug: a bare "UPS" mention used to set a
    `category_hint` spec_filters entry that matched no actual product_spec row
    (nothing was ever ingested with that key), silently zeroing out SQL
    narrowing for every UPS-related query and falling back to fully unscoped
    semantic search. It must now resolve directly to the catalog's real
    category name instead.
    """
    extractor = FilterExtractor(categories={"UPS Solutions", "Automatic Voltage Regulators"})

    filters = await extractor.extract("I need a UPS rated for 5kVA", uuid.uuid4())

    assert filters.category == "UPS Solutions"
    assert "category_hint" not in filters.spec_filters


@pytest.mark.asyncio
async def test_filter_extraction_parses_capacity_requirement() -> None:
    extractor = FilterExtractor()

    filters = await extractor.extract("I need a UPS", uuid.uuid4(), raw_message="I need a 5kVA UPS")

    assert filters.capacity_requirement == Decimal("5")
    assert filters.capacity_unit == "KVA"
    assert filters.has_product_filters() is True


@pytest.mark.asyncio
async def test_filter_extraction_capacity_uses_raw_message_not_just_query() -> None:
    """The reconstructed `query` (e.g. product_interest="UPS") may not carry the
    figure the client actually stated this turn — raw_message must be checked too."""
    extractor = FilterExtractor()

    filters = await extractor.extract(
        "UPS", uuid.uuid4(), raw_message="Mera load around 5kVA hai aur mujhy backup chahiye"
    )

    assert filters.capacity_requirement == Decimal("5")


@pytest.mark.asyncio
async def test_filter_extraction_no_capacity_requirement_when_not_mentioned() -> None:
    extractor = FilterExtractor()

    filters = await extractor.extract("I need a UPS", uuid.uuid4())

    assert filters.capacity_requirement is None
    assert filters.capacity_unit is None


@pytest.mark.asyncio
async def test_filter_extraction_detects_list_all_request() -> None:
    extractor = FilterExtractor(categories={"ups"})

    filters = await extractor.extract("list all your UPS options", uuid.uuid4())

    assert filters.list_all is True


@pytest.mark.asyncio
async def test_filter_extraction_what_products_do_you_have_is_list_all() -> None:
    extractor = FilterExtractor()

    filters = await extractor.extract("what products do you have?", uuid.uuid4())

    assert filters.list_all is True


@pytest.mark.asyncio
async def test_filter_extraction_normal_query_is_not_list_all() -> None:
    extractor = FilterExtractor(categories={"ups"})

    filters = await extractor.extract("I need a UPS for my office", uuid.uuid4())

    assert filters.list_all is False
