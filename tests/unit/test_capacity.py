"""Unit tests for app.rag.capacity — capacity_range and requirement parsing."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.rag.capacity import parse_capacity_range, parse_capacity_requirement

# Every distinct capacity_range value actually present in the ingested catalog.
_REAL_CATALOG_VALUES = (
    "1-10KVA",
    "1-10kVA",
    "1-15kVA",
    "1-3KVA",
    "1-6KVA",
    "1.6-6KVA",
    "10-180KVA",
    "10-20KVA",
    "10-250KVA",
    "10-40KVA",
    "10-60KVA",
    "10-80KVA",
    "100-3000KVA",
    "11KVA",
    "16-32A",
    "160-600KVA",
    "20-150KVA",
    "20-30KVA",
    "20-80kVA",
    "25-200A",
    "3-10KVA",
    "3-5KVA",
    "3-5kVA",
    "300-1200KVA",
    "300-3000KVA",
    "5-30KVA",
    "50-600KVA",
    "6-10KVA",
    "6-10kVA",
    "6-30KVA",
    "60-120KVA",
    "8-20KVA",
)


@pytest.mark.parametrize("value", _REAL_CATALOG_VALUES)
def test_parse_capacity_range_handles_every_real_catalog_value(value: str) -> None:
    parsed = parse_capacity_range(value)

    assert parsed is not None
    assert parsed.min_value <= parsed.max_value
    assert parsed.unit in {"KVA", "A"}


def test_parse_capacity_range_min_max() -> None:
    parsed = parse_capacity_range("1-10KVA")

    assert parsed is not None
    assert parsed.min_value == Decimal("1")
    assert parsed.max_value == Decimal("10")
    assert parsed.unit == "KVA"


def test_parse_capacity_range_single_value_treated_as_a_point() -> None:
    parsed = parse_capacity_range("11KVA")

    assert parsed is not None
    assert parsed.min_value == Decimal("11")
    assert parsed.max_value == Decimal("11")


def test_parse_capacity_range_decimal_bound() -> None:
    parsed = parse_capacity_range("1.6-6KVA")

    assert parsed is not None
    assert parsed.min_value == Decimal("1.6")


def test_parse_capacity_range_amps_unit() -> None:
    parsed = parse_capacity_range("16-32A")

    assert parsed is not None
    assert parsed.unit == "A"
    assert parsed.min_value == Decimal("16")
    assert parsed.max_value == Decimal("32")


def test_parse_capacity_range_case_insensitive_unit() -> None:
    assert parse_capacity_range("6-10kVA") == parse_capacity_range("6-10KVA")


@pytest.mark.parametrize("value", [None, "", "   ", "no numbers here", "48VDC/100Ah"])
def test_parse_capacity_range_returns_none_for_unparseable_input(value: str | None) -> None:
    assert parse_capacity_range(value) is None


def test_parse_capacity_requirement_kva() -> None:
    parsed = parse_capacity_requirement("I need a 5kVA UPS for my office")

    assert parsed is not None
    assert parsed.min_value == parsed.max_value == Decimal("5")
    assert parsed.unit == "KVA"


def test_parse_capacity_requirement_va_converts_to_kva() -> None:
    parsed = parse_capacity_requirement("Something rated 5000VA please")

    assert parsed is not None
    assert parsed.min_value == Decimal("5")
    assert parsed.unit == "KVA"


def test_parse_capacity_requirement_kw_treated_as_kva() -> None:
    parsed = parse_capacity_requirement("my load is about 5kW")

    assert parsed is not None
    assert parsed.min_value == Decimal("5")
    assert parsed.unit == "KVA"


def test_parse_capacity_requirement_amps() -> None:
    parsed = parse_capacity_requirement("I need a static transfer switch rated 20A")

    assert parsed is not None
    assert parsed.min_value == Decimal("20")
    assert parsed.unit == "A"


def test_parse_capacity_requirement_space_between_number_and_unit() -> None:
    parsed = parse_capacity_requirement("we need around 5 kVA of backup power")

    assert parsed is not None
    assert parsed.min_value == Decimal("5")


def test_parse_capacity_requirement_roman_urdu_message_with_embedded_english_unit() -> None:
    """Regression case: the exact real-world phrasing that motivated this feature."""
    parsed = parse_capacity_requirement("Mera load around 5kVA hai aur mujhy 15 minutes ka backup chahiye")

    assert parsed is not None
    assert parsed.min_value == Decimal("5")
    assert parsed.unit == "KVA"


@pytest.mark.parametrize("message", [None, "", "yar mujhy UPS chahiye tha apni karobar ke liye"])
def test_parse_capacity_requirement_returns_none_when_no_figure_present(message: str | None) -> None:
    assert parse_capacity_requirement(message) is None
