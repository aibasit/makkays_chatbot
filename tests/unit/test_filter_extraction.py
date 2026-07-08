"""Unit tests for Module 11 deterministic filter extraction."""

from __future__ import annotations

import uuid

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
