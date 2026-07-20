"""Unit tests for Module 11 deterministic filter extraction."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.rag.filter_extraction import FilterExtractor


@pytest.mark.asyncio
async def test_filter_extraction_finds_brand_category_and_use_case() -> None:
    extractor = FilterExtractor(brands={"Cisco", "Interconnect Solutions"}, categories={"switch", "ups"})

    filters = await extractor.extract(
        "Need a Cisco switch for CCTV",
        uuid.uuid4(),
        intent="sales_inquiry",
    )

    assert filters.brand == "Cisco"
    assert filters.category == "switch"
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
    extractor = FilterExtractor(brands={"Cisco", "Interconnect Solutions"}, categories={"switch"})

    filters = await extractor.extract("Compare Interconnect Solutions and Cisco switch options", uuid.uuid4())

    assert filters.brand == "Interconnect Solutions"


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
async def test_filter_extraction_bare_avr_mention_resolves_to_full_category_name() -> None:
    """Regression test for a real bug found live: "AVR" never literally appears
    inside "Automatic Voltage Regulators", so a bare "AVR" mention resolved to
    no category at all — the query fell back to fully unscoped semantic
    search, and "a three phase AVR for 30kVA" returned UPS Solutions products
    instead (that category is ~3x larger and dominated the ranking) rather
    than any AVR product.
    """
    extractor = FilterExtractor(categories={"UPS Solutions", "Automatic Voltage Regulators"})

    filters = await extractor.extract("Do you have a three phase AVR for 30kVA?", uuid.uuid4())

    assert filters.category == "Automatic Voltage Regulators"


@pytest.mark.asyncio
async def test_filter_extraction_detects_exact_model_code() -> None:
    """Regression test for a real bug found live: exact model-code questions
    ("What are the specs of OH1005T10400S?") were answered "not found" even
    though the model genuinely exists — the code was only ever stored in the
    product's display name and description text, never as its own exact-match
    field, so retrieval fell back to unreliable vector search across the
    whole category. A model code must now resolve to a deterministic
    `spec_filters["model_code"]` entry.
    """
    extractor = FilterExtractor(
        categories={"UPS Solutions"},
        model_codes={"OH1005T10400S", "OH1006T91607S"},
    )

    filters = await extractor.extract(
        "What are the complete specifications of UPS model OH1005T10400S?", uuid.uuid4()
    )

    assert filters.spec_filters["model_code"] == "OH1005T10400S"


@pytest.mark.asyncio
async def test_filter_extraction_model_code_match_is_case_insensitive() -> None:
    extractor = FilterExtractor(model_codes={"OH1005T10400S"})

    filters = await extractor.extract("specs for oh1005t10400s please", uuid.uuid4())

    assert filters.spec_filters["model_code"] == "OH1005T10400S"


@pytest.mark.asyncio
async def test_filter_extraction_no_model_code_when_not_mentioned() -> None:
    extractor = FilterExtractor(model_codes={"OH1005T10400S"})

    filters = await extractor.extract("I need a UPS for 5kVA", uuid.uuid4())

    assert "model_code" not in filters.spec_filters


@pytest.mark.asyncio
async def test_filter_extraction_longer_model_code_wins_over_substring() -> None:
    """A shorter code that happens to be a prefix of a longer one shouldn't
    win just because it was checked first."""
    extractor = FilterExtractor(model_codes={"T300140240S", "T30014024"})

    filters = await extractor.extract("specs for T300140240S", uuid.uuid4())

    assert filters.spec_filters["model_code"] == "T300140240S"


@pytest.mark.asyncio
async def test_filter_extraction_current_message_model_code_wins_over_stale_query() -> None:
    """Regression test for a real bug found live in a multi-turn session: ask
    about UPS OH1005T10400S, then battery RB-LI-512-200, then AVR
    T300140240S in the same conversation — `facts.product_interest` (used as
    `query`) was still "RB-LI-512-200" (never updated to the new question's
    subject), and since `combined_text = f"{query} {raw_message}"` puts the
    stale `query` first, the model-code regex matched the stale battery code
    before ever reaching the AVR code the client actually typed this turn.
    The third answer repeated the second question's battery specs instead of
    answering about the AVR. `raw_message` (this turn's literal text) must
    always be checked before the possibly-stale `query`.
    """
    extractor = FilterExtractor(model_codes={"RB-LI-512-200", "T300140240S"})

    filters = await extractor.extract(
        "RB-LI-512-200",  # stale query, e.g. a leftover `facts.product_interest`
        uuid.uuid4(),
        raw_message="What are the technology, capacity, phase, and voltage class of AVR model T300140240S?",
    )

    assert filters.spec_filters["model_code"] == "T300140240S"


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
async def test_filter_extraction_detects_single_phase() -> None:
    extractor = FilterExtractor()

    filters = await extractor.extract("I need a single-phase UPS", uuid.uuid4())

    assert filters.spec_filters["phase"] == "Single phase"


@pytest.mark.asyncio
async def test_filter_extraction_detects_three_phase() -> None:
    extractor = FilterExtractor()

    filters = await extractor.extract("I need a 3 phase UPS for the server room", uuid.uuid4())

    assert filters.spec_filters["phase"] == "Three phase"


@pytest.mark.asyncio
async def test_filter_extraction_no_phase_when_not_mentioned() -> None:
    extractor = FilterExtractor()

    filters = await extractor.extract("I need a UPS", uuid.uuid4())

    assert "phase" not in filters.spec_filters


@pytest.mark.asyncio
async def test_filter_extraction_detects_list_all_request() -> None:
    extractor = FilterExtractor(categories={"ups"})

    filters = await extractor.extract("list all your UPS options", uuid.uuid4())

    assert filters.list_all is True


@pytest.mark.asyncio
async def test_filter_extraction_singular_category_resolves_to_plural_stored_name() -> None:
    """Regression test for a real bug found live: "list all your Automatic
    Voltage Regulator products" (singular) doesn't literally contain the
    stored category "Automatic Voltage Regulators" (plural), so category
    resolution failed and the request silently fell through to an unscoped,
    all-category list — none of the 52 real AVR products happened to sort
    into the first 50 results alphabetically, so the answer named UPS/
    accessory products instead of any AVR product at all.
    """
    extractor = FilterExtractor(categories={"Automatic Voltage Regulators", "UPS Solutions"})

    filters = await extractor.extract(
        "List all your Automatic Voltage Regulator products with all their features", uuid.uuid4()
    )

    assert filters.category == "Automatic Voltage Regulators"
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


@pytest.mark.asyncio
async def test_filter_extraction_exact_model_code_overrides_list_all_false_positive() -> None:
    """Regression test for a real bug found live: "What are the complete
    specifications of battery model RB-LI-512-200?" matched _LIST_ALL_PATTERN
    on "complete ... model" (a coincidental keyword collision, not an actual
    listing request), which made retrieval bypass the exact model_code SQL
    filter entirely and dump up to `list_all_limit` unrelated products instead
    of the one exact match. An exact model code always means one specific
    product, never a listing request.
    """
    extractor = FilterExtractor(model_codes={"RB-LI-512-200"})

    filters = await extractor.extract(
        "What are the complete specifications of battery model RB-LI-512-200?", uuid.uuid4()
    )

    assert filters.spec_filters["model_code"] == "RB-LI-512-200"
    assert filters.list_all is False


def _constraint(filters, field: str):
    matches = [c for c in filters.constraints if c.field == field]
    assert len(matches) == 1, f"expected exactly one constraint for {field!r}, got {matches}"
    return matches[0]


_CATEGORIES = {"UPS Solutions", "Automatic Voltage Regulators", "Battery Solutions"}


@pytest.mark.asyncio
async def test_filter_extraction_capacity_kva_eq() -> None:
    extractor = FilterExtractor(categories=_CATEGORIES)
    filters = await extractor.extract("I need a UPS rated for 50kVA", uuid.uuid4())
    constraint = _constraint(filters, "capacity_kva")
    assert constraint.operator == "eq"
    assert constraint.value == Decimal("50")


@pytest.mark.asyncio
async def test_filter_extraction_capacity_kva_gte() -> None:
    extractor = FilterExtractor(categories=_CATEGORIES)
    filters = await extractor.extract("I need a UPS rated at least 50 kVA", uuid.uuid4())
    constraint = _constraint(filters, "capacity_kva")
    assert constraint.operator == "gte"
    assert constraint.value == Decimal("50")


@pytest.mark.asyncio
async def test_filter_extraction_gte_does_not_also_set_legacy_exact_capacity() -> None:
    """Regression test for a real bug found live: `capacity_requirement`/
    `capacity_unit` (the legacy exact-containment capacity field) used to be
    set unconditionally alongside the new `capacity_kva` constraint.
    `find_by_filters` ANDs every condition together, so "at least 50 kVA"
    produced a correct `capacity_kva gte 50` constraint *plus* a legacy
    "exactly 50" condition — since no product is exactly 50kVA, the two
    conditions combined always returned zero real candidates, even though
    plenty of 60/80kVA products satisfy "at least 50". The legacy field must
    be skipped once the new constraint already covers the same figure.
    """
    extractor = FilterExtractor(categories=_CATEGORIES)
    filters = await extractor.extract("I need a UPS rated at least 50 kVA", uuid.uuid4())
    assert filters.capacity_requirement is None
    assert filters.capacity_unit is None


@pytest.mark.asyncio
async def test_filter_extraction_capacity_kva_lte() -> None:
    extractor = FilterExtractor(categories=_CATEGORIES)
    filters = await extractor.extract("up to 50kVA UPS please", uuid.uuid4())
    constraint = _constraint(filters, "capacity_kva")
    assert constraint.operator == "lte"
    assert constraint.value == Decimal("50")


@pytest.mark.asyncio
async def test_filter_extraction_capacity_kva_between() -> None:
    extractor = FilterExtractor(categories=_CATEGORIES)
    filters = await extractor.extract("I need a UPS between 30 and 50 kVA", uuid.uuid4())
    constraint = _constraint(filters, "capacity_kva")
    assert constraint.operator == "between"
    assert constraint.value == Decimal("30")
    assert constraint.value_max == Decimal("50")


@pytest.mark.asyncio
async def test_filter_extraction_capacity_kva_nearest() -> None:
    extractor = FilterExtractor(categories=_CATEGORIES)
    filters = await extractor.extract("around 50 kVA UPS", uuid.uuid4())
    constraint = _constraint(filters, "capacity_kva")
    assert constraint.operator == "nearest"
    assert constraint.value == Decimal("50")


@pytest.mark.asyncio
async def test_filter_extraction_capacity_kva_in() -> None:
    extractor = FilterExtractor(categories=_CATEGORIES)
    filters = await extractor.extract("I need a 5 or 6 kVA UPS", uuid.uuid4())
    constraint = _constraint(filters, "capacity_kva")
    assert constraint.operator == "in"
    assert constraint.values == [Decimal("5"), Decimal("6")]


@pytest.mark.asyncio
async def test_filter_extraction_capacity_kva_not_eq() -> None:
    extractor = FilterExtractor(categories=_CATEGORIES)
    filters = await extractor.extract("not a 10 kVA UPS", uuid.uuid4())
    constraint = _constraint(filters, "capacity_kva")
    assert constraint.operator == "not_eq"
    assert constraint.value == Decimal("10")


@pytest.mark.asyncio
async def test_filter_extraction_kw_treated_as_kva_for_ups() -> None:
    extractor = FilterExtractor(categories=_CATEGORIES)
    filters = await extractor.extract("I need a UPS for a 5kW load", uuid.uuid4())
    constraint = _constraint(filters, "capacity_kva")
    assert constraint.value == Decimal("5")


@pytest.mark.asyncio
async def test_filter_extraction_capacity_kva_not_extracted_without_category() -> None:
    """A bare "50kVA" with no resolvable category must not guess which
    category's unit-specific column it belongs to (see the category-aware
    allowlist design)."""
    extractor = FilterExtractor(categories=_CATEGORIES)
    filters = await extractor.extract("I need something rated for 50kVA", uuid.uuid4())
    assert filters.constraints == []


@pytest.mark.asyncio
async def test_filter_extraction_phase_symmetric_for_bare_phase_mention() -> None:
    extractor = FilterExtractor(categories=_CATEGORIES)
    filters = await extractor.extract("I need a three phase UPS", uuid.uuid4())
    assert _constraint(filters, "phase_input_count").value == Decimal("3")
    assert _constraint(filters, "phase_output_count").value == Decimal("3")


@pytest.mark.asyncio
async def test_filter_extraction_phase_split_input_output() -> None:
    extractor = FilterExtractor(categories=_CATEGORIES)
    filters = await extractor.extract(
        "I need a UPS with three phase input and single phase output", uuid.uuid4()
    )
    assert _constraint(filters, "phase_input_count").value == Decimal("3")
    assert _constraint(filters, "phase_output_count").value == Decimal("1")


@pytest.mark.asyncio
async def test_filter_extraction_power_factor() -> None:
    extractor = FilterExtractor(categories=_CATEGORIES)
    filters = await extractor.extract("I need a UPS with power factor 1", uuid.uuid4())
    constraint = _constraint(filters, "power_factor")
    assert constraint.operator == "eq"
    assert constraint.value == Decimal("1")


@pytest.mark.asyncio
async def test_filter_extraction_form_factor_key() -> None:
    extractor = FilterExtractor(categories=_CATEGORIES)
    filters = await extractor.extract("I need a tower UPS", uuid.uuid4())
    constraint = _constraint(filters, "form_factor_key")
    assert constraint.value == "tower"


@pytest.mark.asyncio
async def test_filter_extraction_battery_mode_built_in() -> None:
    extractor = FilterExtractor(categories=_CATEGORIES)
    filters = await extractor.extract("I need a UPS with a built in battery", uuid.uuid4())
    constraint = _constraint(filters, "battery_mode")
    assert constraint.value == "built_in"


@pytest.mark.asyncio
async def test_filter_extraction_parallel_capable() -> None:
    extractor = FilterExtractor(categories=_CATEGORIES)
    filters = await extractor.extract("I need a parallel capable UPS", uuid.uuid4())
    constraint = _constraint(filters, "parallel_capable")
    assert constraint.value == "Yes"


@pytest.mark.asyncio
async def test_filter_extraction_avr_technology_key() -> None:
    extractor = FilterExtractor(categories=_CATEGORIES)
    filters = await extractor.extract("I need a static AVR", uuid.uuid4())
    constraint = _constraint(filters, "technology_key")
    assert constraint.value == "static"


@pytest.mark.asyncio
async def test_filter_extraction_avr_voltage_class() -> None:
    extractor = FilterExtractor(categories=_CATEGORIES)
    filters = await extractor.extract("I need a static AVR for a 400V system", uuid.uuid4())
    constraint = _constraint(filters, "voltage_class_v")
    assert constraint.value == Decimal("400")


@pytest.mark.asyncio
async def test_filter_extraction_battery_voltage_snaps_to_nominal_family() -> None:
    """"410 V battery" should match the real 409.6 V product, not zero results."""
    extractor = FilterExtractor(categories=_CATEGORIES)
    filters = await extractor.extract("a 410V battery", uuid.uuid4())
    constraint = _constraint(filters, "nominal_voltage_vdc")
    assert constraint.value == Decimal("409.6")


@pytest.mark.asyncio
async def test_filter_extraction_battery_voltage_exact_match_not_drifted() -> None:
    extractor = FilterExtractor(categories=_CATEGORIES)
    filters = await extractor.extract("a 512V battery", uuid.uuid4())
    constraint = _constraint(filters, "nominal_voltage_vdc")
    assert constraint.value == Decimal("512")


@pytest.mark.asyncio
async def test_filter_extraction_battery_capacity_ah() -> None:
    extractor = FilterExtractor(categories=_CATEGORIES)
    filters = await extractor.extract("a battery with at least 100 Ah", uuid.uuid4())
    constraint = _constraint(filters, "capacity_ah")
    assert constraint.operator == "gte"
    assert constraint.value == Decimal("100")


@pytest.mark.asyncio
async def test_filter_extraction_battery_energy_kwh_not_confused_with_ups_kva() -> None:
    """A UPS-scoped kVA constraint must never leak onto a battery's kWh field
    (and vice versa) — this is exactly what the category allowlist exists to
    prevent."""
    extractor = FilterExtractor(categories=_CATEGORIES)
    filters = await extractor.extract("a battery with 4.8kWh of energy", uuid.uuid4())
    assert _constraint(filters, "energy_kwh").value == Decimal("4.8")
    assert not any(c.field == "capacity_kva" for c in filters.constraints)


@pytest.mark.asyncio
async def test_filter_extraction_series_key() -> None:
    """`series_key` is scoped to the UPS/AVR allowlists, so the message needs a
    resolvable category — a bare series code with no category signal
    intentionally does not guess which category it belongs to."""
    extractor = FilterExtractor(categories=_CATEGORIES, series_codes={"T-4001", "T-4011"})
    filters = await extractor.extract("do you have the T-4001 UPS in stock", uuid.uuid4())
    constraint = _constraint(filters, "series_key")
    assert constraint.value == "T-4001"
