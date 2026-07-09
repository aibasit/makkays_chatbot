"""Deterministic parsing of product capacity ranges and client power requirements.

Vector similarity search has no notion of numeric range containment — "does 5kVA
fall within this product's 1-10kVA range" is a structured comparison, not a
semantic one. This module turns both the catalog's free-text `capacity_range`
spec ("1-10KVA", "11KVA", "16-32A") and a client's stated requirement ("5kVA",
"5000VA", "20A") into a common `ParsedCapacity(min, max, unit)` shape so a real
`min <= requirement <= max` SQL comparison becomes possible.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import NamedTuple

# "1-10KVA", "1.6-6kVA", "11KVA", "16-32A": an optional "min-" prefix, a required
# number, then a unit made of letters only. Matches every capacity_range format
# actually present in the catalog.
_CAPACITY_RANGE_PATTERN = re.compile(
    r"^\s*(?P<min>\d+(?:\.\d+)?)\s*(?:-\s*(?P<max>\d+(?:\.\d+)?))?\s*(?P<unit>[A-Za-z]+)\s*$"
)

# A power figure mentioned in free-text client messages, e.g. "5kVA", "5000VA",
# "5 kW", "20A". The unit alternatives are checked most-specific-first so "kva"
# isn't shadowed by a looser "va" match.
_REQUIREMENT_PATTERN = re.compile(
    r"\b(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>kva|va|kw|w|amps?|a)\b",
    re.IGNORECASE,
)

_KILO_UNITS = frozenset({"kva", "kw"})
_BASE_UNITS = frozenset({"va", "w"})
_AMP_UNITS = frozenset({"a", "amp", "amps"})


class ParsedCapacity(NamedTuple):
    """A numeric capacity/power range with a normalized unit ("KVA" or "A")."""

    min_value: Decimal
    max_value: Decimal
    unit: str


def parse_capacity_range(text: str | None) -> ParsedCapacity | None:
    """Parse a catalog `capacity_range` spec string, e.g. "1-10KVA" or "11KVA"."""
    if not text:
        return None
    match = _CAPACITY_RANGE_PATTERN.match(text.strip())
    if not match:
        return None
    try:
        min_value = Decimal(match.group("min"))
        max_value = Decimal(match.group("max")) if match.group("max") else min_value
    except InvalidOperation:
        return None
    unit = _normalize_catalog_unit(match.group("unit"))
    if unit is None:
        return None
    if min_value > max_value:
        min_value, max_value = max_value, min_value
    return ParsedCapacity(min_value=min_value, max_value=max_value, unit=unit)


def parse_capacity_requirement(message: str | None) -> ParsedCapacity | None:
    """Parse a client's stated power requirement from free text, e.g. "5kVA".

    kW/W are treated as approximately equal to kVA (a common, deliberately
    conservative simplification — a UPS sized by kVA covers the equivalent kW
    load at unity-or-lower power factor).
    """
    if not message:
        return None
    match = _REQUIREMENT_PATTERN.search(message)
    if not match:
        return None
    try:
        value = Decimal(match.group("value"))
    except InvalidOperation:
        return None
    raw_unit = match.group("unit").lower()
    if raw_unit in _BASE_UNITS:
        value = value / Decimal(1000)
        unit = "KVA"
    elif raw_unit in _KILO_UNITS:
        unit = "KVA"
    elif raw_unit in _AMP_UNITS:
        unit = "A"
    else:
        return None
    return ParsedCapacity(min_value=value, max_value=value, unit=unit)


def _normalize_catalog_unit(raw_unit: str) -> str | None:
    lowered = raw_unit.lower()
    if lowered == "kva":
        return "KVA"
    if lowered == "a":
        return "A"
    return None
