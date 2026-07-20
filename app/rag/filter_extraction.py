"""Deterministic structured filter extraction for RAG queries."""

from __future__ import annotations

import re
from collections.abc import Callable
from decimal import Decimal
from uuid import UUID

from app.logging_config import get_logger
from app.rag.capacity import parse_capacity_requirement
from app.rag.repository import ProductRepository
from app.rag.schemas import Constraint, ExtractedFilters

logger = get_logger(__name__)

_NUMBER = r"\d+(?:\.\d+)?"

# ---------------------------------------------------------------------------
# Category resolution
# ---------------------------------------------------------------------------

# Category names an abbreviation doesn't literally appear inside of — a plain
# substring match against the vocabulary silently finds nothing for these,
# which used to make the *whole* SQL narrowing query return unscoped results
# (falling back to ranking across every category, where the largest category
# tends to dominate). "UPS" is a literal substring of "UPS Solutions" so it
# doesn't strictly need this, but is kept for robustness against a renamed
# category; "AVR" never appears inside "Automatic Voltage Regulators" at all,
# which is exactly the same class of bug the original "UPS" fix addressed —
# found live when "a three phase AVR for 30kVA" returned UPS products instead,
# because "AVR" alone resolved to no category and the filter fell through.
_CATEGORY_ABBREVIATIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bups\b", re.IGNORECASE), "ups"),
    (re.compile(r"\bavr\b", re.IGNORECASE), "voltage regulator"),
    # "battery"/"batteries" is a plain word in the message but the stored
    # category is "Battery Solutions" — `_first_vocabulary_match` only ever
    # matches when the *full* category string appears in the message, so a
    # bare "battery" mention needs the same abbreviation-table treatment as
    # "UPS"/"AVR" above, or category (and therefore every battery-specific
    # constraint field gated behind it, e.g. nominal_voltage_vdc) never
    # resolves. Found live: "a 410V battery" produced zero constraints.
    (re.compile(r"\bbatter(?:y|ies)\b", re.IGNORECASE), "battery"),
)

# Maps a *resolved* category string (whatever the live catalog actually calls
# it — "UPS Solutions", "Automatic Voltage Regulators", "Battery Solutions")
# to a normalized "category key" used only to scope which constraint fields
# are attempted below. Substring-matched against the lowercased category so a
# catalog rename doesn't silently break this, same reasoning as the
# abbreviation table above.
_CATEGORY_KEY_SUBSTRINGS: tuple[tuple[str, str], ...] = (
    ("ups", "ups"),
    ("voltage regulator", "avr"),
    ("battery", "battery"),
)

# Which constraint `field`s are even valid to extract for a given resolved
# category — prevents a battery's voltage from being interpreted as an AVR's
# `voltage_class_v`, a UPS's kVA rating leaking onto a battery search, etc.
# Some fields are listed but have no client-message detector wired yet
# (sub_category_key, product_type_key, service_life_type) — they're reserved
# here so the allowlist doesn't need revisiting when a detector is added; they
# simply never appear in `constraints` today.
_ALLOWED_CONSTRAINT_FIELDS: dict[str, frozenset[str]] = {
    "ups": frozenset(
        {
            "capacity_kva", "power_factor", "current_a",
            "phase_input_count", "phase_output_count",
            "form_factor_key", "battery_mode", "parallel_capable",
            "series_key", "sub_category_key", "product_type_key",
        }
    ),
    "avr": frozenset(
        {
            "capacity_kva", "phase_input_count", "phase_output_count",
            "technology_key", "voltage_class_v", "series_key", "sub_category_key",
        }
    ),
    "battery": frozenset(
        {
            "nominal_voltage_vdc", "capacity_ah", "energy_kwh", "chemistry_key",
            "max_discharge_power_kw", "max_parallel_units", "service_life_years",
            "service_life_type", "sub_category_key",
        }
    ),
}

# Spec keys fetched as live categorical vocabulary (see `_vocabulary`) for the
# detectors that need to recognize an exact stored value (series codes).
_VOCAB_SPEC_KEYS = frozenset({"series"})


def _category_key(category: str | None) -> str | None:
    if not category:
        return None
    lowered = category.lower()
    for substring, key in _CATEGORY_KEY_SUBSTRINGS:
        if substring in lowered:
            return key
    return None


def _allowed_fields_for(category_key: str | None) -> frozenset[str] | None:
    """Return the constraint-field allowlist for a category, or `None` for "no restriction".

    `None` (category unresolved) intentionally does *not* mean "everything
    allowed" at the call sites below — each unit-specific detector only fires
    when its own field is explicitly permitted for the resolved category, so
    an unresolved category simply means those detectors stay silent rather
    than guessing which category's units a bare number belongs to.
    """
    if category_key is None:
        return None
    return _ALLOWED_CONSTRAINT_FIELDS.get(category_key, frozenset())


# ---------------------------------------------------------------------------
# Phase (split into input/output counts)
# ---------------------------------------------------------------------------

_PHASE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bthree[\s-]?phase\b|\b3[\s-]?phase\b", re.IGNORECASE), "Three phase"),
    (re.compile(r"\bsingle[\s-]?phase\b|\b1[\s-]?phase\b", re.IGNORECASE), "Single phase"),
)
_PHASE_TO_COUNT = {"Three phase": 3, "Single phase": 1}

# "three-phase input, single-phase output" / "3-in, 1-out" — more specific
# than a bare "three phase" mention, checked first so a split request isn't
# collapsed into one symmetric phase count.
_SPLIT_PHASE_PATTERN = re.compile(
    r"\b(?P<in_word>1|3|single|three)[\s-]?(?:phase)?[\s-]*(?:-in\b|input)\b.{0,25}?"
    r"(?P<out_word>1|3|single|three)[\s-]?(?:phase)?[\s-]*(?:-out\b|output)\b",
    re.IGNORECASE,
)


def _phase_word_to_count(word: str) -> int:
    return 1 if word.lower() in ("1", "single") else 3


def _extract_phase_constraints(text: str) -> list[Constraint]:
    split_match = _SPLIT_PHASE_PATTERN.search(text)
    if split_match:
        return [
            Constraint(
                field="phase_input_count", operator="eq",
                value=Decimal(_phase_word_to_count(split_match.group("in_word"))),
                source_text=split_match.group(0),
            ),
            Constraint(
                field="phase_output_count", operator="eq",
                value=Decimal(_phase_word_to_count(split_match.group("out_word"))),
                source_text=split_match.group(0),
            ),
        ]
    for pattern, phase_value in _PHASE_PATTERNS:
        match = pattern.search(text)
        if match:
            count = Decimal(_PHASE_TO_COUNT[phase_value])
            return [
                Constraint(field="phase_input_count", operator="eq", value=count, source_text=match.group(0)),
                Constraint(field="phase_output_count", operator="eq", value=count, source_text=match.group(0)),
            ]
    return []


# ---------------------------------------------------------------------------
# Generic unit-aware numeric constraint engine
# ---------------------------------------------------------------------------
# Supports eq ("50kVA"), gte ("at least 50kVA"), lte ("up to 50kVA"),
# between ("between 30 and 50kVA"), in ("5 or 6 kVA"), not_eq ("not 10kVA"),
# and nearest ("around 50kVA") for any field with a "<number><unit>" style
# mention — reused across capacity_kva, current_a, nominal_voltage_vdc,
# capacity_ah, and energy_kwh rather than duplicating the same parsing five
# times.

_OPERATOR_BEFORE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:at\s+least|minimum(?:\s+of)?|no\s+less\s+than)\s*$", re.IGNORECASE), "gte"),
    (re.compile(r"\b(?:up\s+to|maximum(?:\s+of)?|no\s+more\s+than)\s*$", re.IGNORECASE), "lte"),
    (re.compile(r"\b(?:around|about|approximately|roughly|nearly)\s*$", re.IGNORECASE), "nearest"),
    (re.compile(r"\b(?:not|excluding|other\s+than)(?:\s+a)?\s*$", re.IGNORECASE), "not_eq"),
)
_OPERATOR_AFTER_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^\s*(?:or\s+more|and\s+(?:up|above))\b", re.IGNORECASE), "gte"),
    (re.compile(r"^\s*(?:or\s+less|and\s+(?:below|under))\b", re.IGNORECASE), "lte"),
)
_OPERATOR_CONTEXT_WINDOW = 20


def _detect_operator(text: str, start: int, end: int) -> str:
    before = text[max(0, start - _OPERATOR_CONTEXT_WINDOW) : start]
    for pattern, operator in _OPERATOR_BEFORE_PATTERNS:
        if pattern.search(before):
            return operator
    after = text[end : end + _OPERATOR_CONTEXT_WINDOW]
    for pattern, operator in _OPERATOR_AFTER_PATTERNS:
        if pattern.match(after):
            return operator
    return "eq"


def _find_between(text: str, unit_pattern: str) -> tuple[Decimal, Decimal, str] | None:
    pattern = re.compile(
        rf"\bbetween\s+({_NUMBER})\s*(?:and|-|to)\s*({_NUMBER})\s*({unit_pattern})\b", re.IGNORECASE
    )
    match = pattern.search(text)
    if not match:
        return None
    lo, hi = Decimal(match.group(1)), Decimal(match.group(2))
    unit = match.group(3).lower()
    return (lo, hi, unit) if lo <= hi else (hi, lo, unit)


def _find_in_values(text: str, unit_pattern: str) -> tuple[list[Decimal], str] | None:
    pattern = re.compile(
        rf"\b({_NUMBER})\s*(?:{unit_pattern})?\s+or\s+({_NUMBER})\s*({unit_pattern})\b", re.IGNORECASE
    )
    match = pattern.search(text)
    if not match:
        return None
    return [Decimal(match.group(1)), Decimal(match.group(2))], match.group(3).lower()


def _find_single(text: str, unit_pattern: str) -> tuple[Decimal, str, int, int] | None:
    pattern = re.compile(rf"\b({_NUMBER})\s*({unit_pattern})\b", re.IGNORECASE)
    match = pattern.search(text)
    if not match:
        return None
    return Decimal(match.group(1)), match.group(2).lower(), match.start(), match.end()


def _extract_numeric_constraint(
    text: str,
    field: str,
    unit_pattern: str,
    *,
    normalize: Callable[[Decimal, str], Decimal] = lambda value, _unit: value,
    unit_label: str,
) -> Constraint | None:
    """Extract at most one constraint for `field` from `text` (between > in > single)."""
    between = _find_between(text, unit_pattern)
    if between is not None:
        lo, hi, unit = between
        return Constraint(
            field=field, operator="between",
            value=normalize(lo, unit), value_max=normalize(hi, unit),
            unit=unit_label, source_text=text,
        )
    in_values = _find_in_values(text, unit_pattern)
    if in_values is not None:
        values, unit = in_values
        return Constraint(
            field=field, operator="in",
            values=[normalize(value, unit) for value in values],
            unit=unit_label, source_text=text,
        )
    single = _find_single(text, unit_pattern)
    if single is None:
        return None
    raw_value, raw_unit, start, end = single
    operator = _detect_operator(text, start, end)
    return Constraint(
        field=field, operator=operator, value=normalize(raw_value, raw_unit),
        unit=unit_label, source_text=text,
    )


def _normalize_kva(value: Decimal, raw_unit: str) -> Decimal:
    # kW/W are treated as approximately equal to kVA — the same deliberate,
    # conservative simplification `app.rag.capacity` already makes for the
    # legacy `capacity_requirement` field (a UPS sized by kVA covers the
    # equivalent kW load at unity-or-lower power factor).
    if raw_unit in ("va", "w"):
        return value / Decimal(1000)
    return value


_VOLTAGE_NOMINAL_FAMILIES: tuple[Decimal, ...] = (
    Decimal("48"), Decimal("96"), Decimal("192"), Decimal("230"),
    Decimal("400"), Decimal("409.6"), Decimal("480"), Decimal("512"),
)
_VOLTAGE_TOLERANCE = Decimal("0.02")  # +/- 2%


def _snap_to_nominal_voltage(value: Decimal, _raw_unit: str) -> Decimal:
    """Snap a client-stated battery voltage to the nearest known nominal family.

    "410 V battery" should match a real 409.6 V product; "512 V battery"
    should match 512 V exactly and not drift onto a neighboring family. A
    fixed table of known nominal voltages (not a blanket percentage) keeps
    this from conflating two genuinely distinct products that just happen to
    be numerically close.
    """
    for family in _VOLTAGE_NOMINAL_FAMILIES:
        if abs(value - family) <= family * _VOLTAGE_TOLERANCE:
            return family
    return value


# ---------------------------------------------------------------------------
# Power factor
# ---------------------------------------------------------------------------

_POWER_FACTOR_PATTERN = re.compile(r"\b(?:power\s*factor|pf)\s*(?:of|=|:)?\s*(\d(?:\.\d+)?)\b", re.IGNORECASE)


def _extract_power_factor_constraint(text: str) -> Constraint | None:
    match = _POWER_FACTOR_PATTERN.search(text)
    if not match:
        return None
    operator = _detect_operator(text, match.start(), match.end())
    return Constraint(
        field="power_factor", operator=operator, value=Decimal(match.group(1)), source_text=match.group(0)
    )


# ---------------------------------------------------------------------------
# Categorical fields (technology, form factor, battery configuration, ...)
# ---------------------------------------------------------------------------

_TECHNOLOGY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bservo\b", re.IGNORECASE), "servo"),
    (re.compile(r"\bstatic\b(?!\s+transfer)", re.IGNORECASE), "static"),
)
_FORM_FACTOR_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\brack\s*/\s*tower\b|\brack[\s-]?tower\s+convert", re.IGNORECASE), "rack_tower_convertible"),
    (re.compile(r"\brack[\s-]?mount(?:ed|able)?\b", re.IGNORECASE), "rack_mount"),
    (re.compile(r"\bwall[\s-]?mount(?:ed)?\b", re.IGNORECASE), "wall_mount"),
    (re.compile(r"\bmodular\b", re.IGNORECASE), "modular"),
    (re.compile(r"\btower\b", re.IGNORECASE), "tower"),
)
_BATTERY_MODE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"\bbuilt[\s-]?in\b.{0,15}\bexternal\b|\bexternal\b.{0,15}\bbuilt[\s-]?in\b",
            re.IGNORECASE,
        ),
        "built_in_and_external",
    ),
    (re.compile(r"\blithium[\s-]?(?:ion)?\s+compat", re.IGNORECASE), "lithium_compatible"),
    (re.compile(r"\bbuilt[\s-]?in\b", re.IGNORECASE), "built_in"),
    (re.compile(r"\bexternal\b|\blong\s+back[\s-]?up\b", re.IGNORECASE), "external"),
)
_CHEMISTRY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\blifepo\s*4?\b|\blithium\s+iron\s+phosphate\b", re.IGNORECASE), "lifepo4"),
)
_NOT_PARALLEL_PATTERN = re.compile(r"\b(?:not|non|no)[\s-]?parallel", re.IGNORECASE)
_PARALLEL_CAPABLE_PATTERN = re.compile(r"\bparallel(?:[\s-]?capable)?\b", re.IGNORECASE)


def _first_categorical_match(text: str, patterns: tuple[tuple[re.Pattern[str], str], ...]) -> str | None:
    for pattern, value in patterns:
        if pattern.search(text):
            return value
    return None


def _extract_parallel_capable_constraint(text: str) -> Constraint | None:
    if _NOT_PARALLEL_PATTERN.search(text):
        return Constraint(field="parallel_capable", operator="eq", value="No", source_text="not parallel")
    if _PARALLEL_CAPABLE_PATTERN.search(text):
        return Constraint(field="parallel_capable", operator="eq", value="Yes", source_text="parallel capable")
    return None


# ---------------------------------------------------------------------------
# List-all / use-case / doc-type (unchanged from the pre-constraint extractor)
# ---------------------------------------------------------------------------

_LIST_ALL_PATTERN = re.compile(
    r"\b(?:all|every|entire|full|complete)\b[^.?!]{0,30}\b(?:products?|options?|models?|"
    r"range|lineup|list|catalog|types?)\b"
    r"|\blist\s+(?:all|every)\b"
    r"|\bwhat\s+(?:products?|options?|models?)\s+do\s+you\s+(?:have|offer|carry|sell)\b",
    re.IGNORECASE,
)

_USE_CASES: tuple[str, ...] = (
    "school", "hospital", "office", "data center", "datacenter", "cctv", "enterprise", "smb",
)

INTENT_DOC_TYPE_MAP: dict[str, str] = {
    "installation_guidance": "installation_guide",
    "warranty_information": "warranty_doc",
    "troubleshooting": "manual",
    "technical_support": "technical_doc",
}


class FilterExtractor:
    """Extract brand/category/spec/doc filters and unit-aware constraints without using the LLM."""

    def __init__(
        self,
        product_repository: ProductRepository | None = None,
        *,
        brands: set[str] | frozenset[str] | None = None,
        categories: set[str] | frozenset[str] | None = None,
        model_codes: set[str] | frozenset[str] | None = None,
        series_codes: set[str] | frozenset[str] | None = None,
    ) -> None:
        self.product_repository = product_repository
        self._static_brands = frozenset(brands or [])
        self._static_categories = frozenset(categories or [])
        self._static_model_codes = frozenset(model_codes or [])
        self._static_series_codes = frozenset(series_codes or [])
        self._vocabulary_cache: dict[UUID, tuple[frozenset[str], frozenset[str], frozenset[str], frozenset[str]]] = {}

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
        brands, categories, model_codes, series_codes = await self._vocabulary(tenant_id)
        lowered = combined_text.lower()
        spec_filters: dict[str, str] = {}

        for pattern, phase_value in _PHASE_PATTERNS:
            if pattern.search(combined_text):
                spec_filters["phase"] = phase_value
                break

        # Check `raw_message` (this turn's literal text) before falling back to
        # `combined_text`. `_first_model_code_match` returns whichever code
        # occurs *earliest* in the string it's given, and `combined_text` puts
        # `query` first — so a stale `query` (facts.product_interest carried
        # over from an earlier turn, e.g. still "RB-LI-512-200" from a prior
        # battery question) would win over the code the client actually typed
        # *this* turn. Found live in a real multi-turn session: asking about
        # UPS OH1005T10400S, then battery RB-LI-512-200, then AVR T300140240S
        # in sequence made the third answer repeat the second question's
        # battery specs, because the stale battery code matched first.
        model_code = _first_model_code_match(raw_message, model_codes) if raw_message else None
        if model_code is None:
            model_code = _first_model_code_match(combined_text, model_codes)
        if model_code is not None:
            # An exact model code (e.g. "OH1005T10400S") is a reliable, unique
            # lookup key stored as its own spec — this bypasses vector search
            # entirely for this candidate set, which matters because dense
            # embeddings are unreliable at pinpointing one exact alphanumeric
            # code among many near-identical descriptions.
            spec_filters["model_code"] = model_code

        category = _first_vocabulary_match(combined_text, categories)
        if category is None:
            for pattern, substring in _CATEGORY_ABBREVIATIONS:
                if pattern.search(combined_text):
                    category = _first_category_containing(categories, substring)
                    if category:
                        break
        if category is None:
            category = _first_singular_category_match(combined_text, categories)

        category_key = _category_key(category)
        allowed = _allowed_fields_for(category_key)
        constraints = self._extract_constraints(
            combined_text, raw_message, category_key, allowed, series_codes
        )

        use_case = _first_literal_match(lowered, _USE_CASES)
        doc_type = INTENT_DOC_TYPE_MAP.get(intent or "")
        # Skip the legacy exact-containment capacity check when the new
        # constraint system already produced a `capacity_kva`/`current_a`
        # constraint for this message — both represent the *same* client-
        # stated figure, and `find_by_filters` ANDs every condition together.
        # The legacy field only ever means "capacity_min <= x <= capacity_max"
        # (an exact-containment check), so combining it with e.g. a `gte`
        # constraint silently added "AND also exactly this value" on top of
        # "at least this value" — found live: "at least 50 kVA" resolved a
        # correct `capacity_kva gte 50` constraint, but the legacy field also
        # matched only products at *exactly* 50kVA (none exist), so the two
        # conditions ANDed together always returned zero real candidates.
        has_new_capacity_constraint = any(c.field in ("capacity_kva", "current_a") for c in constraints)
        capacity = None if has_new_capacity_constraint else parse_capacity_requirement(combined_text)
        # An exact model code always means one specific product, never a
        # listing request — without this guard, "complete specifications of
        # battery model RB-LI-512-200" false-matched _LIST_ALL_PATTERN on
        # "complete ... model" and dumped up to `list_all_limit` unrelated
        # products instead of narrowing to the one exact match, since the
        # list-all branch bypasses `find_by_filters`/the model_code spec
        # filter entirely. Found live: this made an exact-model-code question
        # fail whenever it also happened to contain "complete"/"full"/"all".
        list_all = model_code is None and bool(_LIST_ALL_PATTERN.search(combined_text))

        filters = ExtractedFilters(
            brand=_first_vocabulary_match(combined_text, brands),
            category=category,
            spec_filters=spec_filters,
            doc_type=doc_type,
            use_case=use_case,
            capacity_requirement=capacity.min_value if capacity else None,
            capacity_unit=capacity.unit if capacity else None,
            constraints=constraints,
            list_all=list_all,
        )
        logger.debug(
            "rag_filters_extracted",
            extra={
                "tenant_id": str(tenant_id),
                "brand": filters.brand,
                "category": filters.category,
                "spec_filters": filters.spec_filters,
                "constraints": [c.model_dump(mode="json") for c in filters.constraints],
                "doc_type": filters.doc_type,
                "use_case": filters.use_case,
                "capacity_requirement": str(filters.capacity_requirement) if filters.capacity_requirement else None,
                "capacity_unit": filters.capacity_unit,
                "list_all": filters.list_all,
            },
        )
        return filters

    def _extract_constraints(
        self,
        combined_text: str,
        raw_message: str | None,
        category_key: str | None,
        allowed: frozenset[str] | None,
        series_codes: frozenset[str],
    ) -> list[Constraint]:
        """Build the category-scoped constraint list.

        Each unit-specific detector only runs when its field is in `allowed`
        (the resolved category's allowlist) — with an unresolved category,
        `allowed` is `None` and every category-scoped detector below is
        skipped, so an ambiguous bare figure never guesses which category's
        units it belongs to (see `_allowed_fields_for`'s docstring). Phase and
        model-code detection stay category-agnostic per `_CATEGORY_AGNOSTIC_FIELDS`
        and the phase columns are shared by UPS/AVR only via their own allowlists.
        """
        constraints: list[Constraint] = []

        def _allow(field: str) -> bool:
            return allowed is not None and field in allowed

        if _allow("phase_input_count") or _allow("phase_output_count"):
            constraints.extend(_extract_phase_constraints(combined_text))

        if _allow("capacity_kva"):
            constraint = _extract_numeric_constraint(
                combined_text, "capacity_kva", r"kva|va|kw|w", normalize=_normalize_kva, unit_label="KVA"
            )
            if constraint:
                constraints.append(constraint)

        if _allow("power_factor"):
            constraint = _extract_power_factor_constraint(combined_text)
            if constraint:
                constraints.append(constraint)

        if _allow("current_a"):
            constraint = _extract_numeric_constraint(
                combined_text, "current_a", r"amps|amp|a", unit_label="A"
            )
            if constraint:
                constraints.append(constraint)

        if _allow("form_factor_key"):
            value = _first_categorical_match(combined_text, _FORM_FACTOR_PATTERNS)
            if value:
                constraints.append(Constraint(field="form_factor_key", operator="eq", value=value))

        if _allow("battery_mode"):
            value = _first_categorical_match(combined_text, _BATTERY_MODE_PATTERNS)
            if value:
                constraints.append(Constraint(field="battery_mode", operator="eq", value=value))

        if _allow("parallel_capable"):
            constraint = _extract_parallel_capable_constraint(combined_text)
            if constraint:
                constraints.append(constraint)

        if _allow("technology_key"):
            value = _first_categorical_match(combined_text, _TECHNOLOGY_PATTERNS)
            if value:
                constraints.append(Constraint(field="technology_key", operator="eq", value=value))

        if _allow("voltage_class_v"):
            constraint = _extract_numeric_constraint(
                combined_text, "voltage_class_v", r"vdc|volts|volt|v", unit_label="V"
            )
            if constraint:
                constraints.append(constraint)

        if _allow("nominal_voltage_vdc"):
            constraint = _extract_numeric_constraint(
                combined_text, "nominal_voltage_vdc", r"vdc|volts|volt|v",
                normalize=_snap_to_nominal_voltage, unit_label="VDC",
            )
            if constraint:
                constraints.append(constraint)

        if _allow("capacity_ah"):
            constraint = _extract_numeric_constraint(combined_text, "capacity_ah", r"ah", unit_label="AH")
            if constraint:
                constraints.append(constraint)

        if _allow("energy_kwh"):
            constraint = _extract_numeric_constraint(combined_text, "energy_kwh", r"kwh", unit_label="KWH")
            if constraint:
                constraints.append(constraint)

        if _allow("chemistry_key"):
            value = _first_categorical_match(combined_text, _CHEMISTRY_PATTERNS)
            if value:
                constraints.append(Constraint(field="chemistry_key", operator="eq", value=value))

        if _allow("series_key"):
            series = _first_model_code_match(raw_message, series_codes) if raw_message else None
            if series is None:
                series = _first_model_code_match(combined_text, series_codes)
            if series is not None:
                constraints.append(Constraint(field="series_key", operator="eq", value=series))

        return constraints

    async def _vocabulary(
        self, tenant_id: UUID
    ) -> tuple[frozenset[str], frozenset[str], frozenset[str], frozenset[str]]:
        if self.product_repository is None:
            return (
                self._static_brands, self._static_categories,
                self._static_model_codes, self._static_series_codes,
            )
        cached = self._vocabulary_cache.get(tenant_id)
        if cached is not None:
            return cached
        brands, categories = await self.product_repository.get_distinct_values(tenant_id)
        model_codes = await self.product_repository.get_distinct_model_codes(tenant_id)
        spec_vocab = await self.product_repository.get_distinct_spec_value_map(tenant_id, _VOCAB_SPEC_KEYS)
        series_codes = spec_vocab.get("series", frozenset())
        if self._static_brands:
            brands = brands | self._static_brands
        if self._static_categories:
            categories = categories | self._static_categories
        if self._static_model_codes:
            model_codes = model_codes | self._static_model_codes
        if self._static_series_codes:
            series_codes = series_codes | self._static_series_codes
        result = (brands, categories, model_codes, series_codes)
        self._vocabulary_cache[tenant_id] = result
        return result


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


def _first_model_code_match(query: str, model_codes: frozenset[str]) -> str | None:
    """Return the exact stored code (model code or series code) the message mentions, if any.

    A dedicated matcher rather than reusing `_first_vocabulary_match` — these
    vocabularies can run into the hundreds, so this builds one combined regex
    (single compile, single search) instead of compiling one pattern per
    candidate. Longest-first ordering guards against a short code matching as
    a substring of a longer one that also appears in the message.
    """
    if not model_codes:
        return None
    ordered = sorted(model_codes, key=len, reverse=True)
    pattern = re.compile(
        r"(?<!\w)(?:" + "|".join(re.escape(code) for code in ordered) + r")(?!\w)",
        re.IGNORECASE,
    )
    match = pattern.search(query)
    if not match:
        return None
    matched_text = match.group(0)
    for code in model_codes:
        if code.lower() == matched_text.lower():
            return code
    return matched_text


def _first_category_containing(categories: frozenset[str], substring: str) -> str | None:
    matches = sorted(value for value in categories if substring.lower() in value.lower())
    return matches[0] if matches else None


def _singular(value: str) -> str | None:
    """Strip one trailing "s" (not "ss"), or `None` if the value doesn't end in one."""
    if value.endswith("s") and not value.endswith("ss"):
        return value[:-1]
    return None


def _first_singular_category_match(query: str, categories: frozenset[str]) -> str | None:
    """Match a category spelled out in singular form against the (plural) stored name.

    `_first_vocabulary_match` requires the *exact* stored category string as a
    substring — a client writing out "Automatic Voltage Regulator" (singular)
    never literally contains the stored "Automatic Voltage Regulators"
    (plural), so it fails category resolution and falls through to an
    unscoped, all-category `list_all`. Found live: "list all your Automatic
    Voltage Regulator products" returned UPS/accessory products instead of any
    AVR product at all, since none happened to sort into the first 50 results
    alphabetically across the whole catalog.
    """
    singular_to_real: dict[str, str] = {}
    for value in categories:
        singular = _singular(value)
        if singular:
            singular_to_real[singular] = value
    matched = _first_vocabulary_match(query, frozenset(singular_to_real))
    return singular_to_real.get(matched) if matched else None


def _first_literal_match(lowered_query: str, values: tuple[str, ...]) -> str | None:
    matches = [(lowered_query.find(value), value) for value in values if value in lowered_query]
    matches = [item for item in matches if item[0] >= 0]
    if not matches:
        return None
    matches.sort(key=lambda item: item[0])
    value = matches[0][1]
    return "data_center" if value in {"data center", "datacenter"} else value
