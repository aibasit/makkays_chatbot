"""Wire the `Updated Knowledge files/ipower_{UPS,AVR,Battery}_refined.xlsx`
catalogs into the live retrieval path — Postgres `products`/`product_specs`/
`product_pricing` plus the `products_v1` Qdrant collection.

Supersedes `scripts/ingest_ipower_model_catalog.py` (the JSONL-based
pipeline): same 239 model-level UPS/AVR/Battery products (181 + 52 + 6), but
sourced from the cleaner "refined" spreadsheets, which carry real typed
columns (Capacity (kVA), Power Factor, Current (A), Nominal Voltage (VDC), ...)
instead of only free-text spec strings. This script populates *both*:

  1. The unit-specific typed columns on `products` added in migration 0014
     (`capacity_kva`, `power_factor`, `phase_input_count`, ...) — what
     `ProductRepository.find_by_filters`'s new `Constraint` operator support
     (eq/gte/lte/between/in/not_eq/nearest) actually filters on.
  2. The same human-readable `product_specs` rows the old pipeline wrote
     (`domain`, `subcategory`, `model_code`, `phase`, `form_factor`, ...),
     plus a handful of new normalized "_key" specs (`technology_key`,
     `form_factor_key`, `battery_mode`, `chemistry_key`) — these are what
     `ProductRepository.get_specs_for_products` returns for grounding the
     final LLM answer, which reads from `product_specs`, not the typed
     columns. Filtering and display are two separate concerns; both need
     populating at ingestion, or a field would filter correctly but never
     appear in a spec-explainer/comparison answer (or vice versa).

Each row's `RAG Chunk Text` column is a pre-authored, self-contained
natural-language chunk (specs + series description + applications fused
together) — used directly as both `description` and the embedding input text,
rather than reconstructing prose from specs like the old script did.

Categories match the live catalog's existing naming exactly (all UPS-sheet
rows — including its internal Inverter/Accessory sub-rows — go to "UPS
Solutions", matching what's already live; "Inverter Solutions"/"Optional /
Accessories" are separate, older categories from a different source and are
deliberately left untouched here).

Run (inside Docker):

    docker compose run --rm --no-deps backend python -m scripts.ingest_ipower_refined_catalog \
        --tenant-id $DEFAULT_TENANT_ID

Not idempotent, per this project's established ingestion convention — delete
existing rows first if re-running:

    DELETE FROM products WHERE tenant_id = '<tenant>' AND category IN
        ('UPS Solutions', 'Automatic Voltage Regulators', 'Battery Solutions');
"""

from __future__ import annotations

import argparse
import asyncio
import math
import re
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pandas as pd

from app.db.engine import dispose_database, get_sessionmaker, initialize_database
from app.dependencies import get_settings
from app.quotes.repository import ProductPricingRepository
from app.rag.ingestion import IngestionService
from app.rag.retrieval_service import PRODUCT_COLLECTION
from app.rag.schemas import ProductIngestRecord

_SOURCE_DIR = Path("Updated Knowledge files")
_BRAND = "Interconnect Solutions"
_MIN_PRICE = Decimal("150")

_UPS_CATEGORY = "UPS Solutions"
_AVR_CATEGORY = "Automatic Voltage Regulators"
_BATTERY_CATEGORY = "Battery Solutions"

_FORM_FACTOR_KEY_MAP: dict[str, str] = {
    "Tower": "tower",
    "Rack-mount": "rack_mount",
    "Rack/Tower convertible": "rack_tower_convertible",
    "Modular power module": "modular",
    "Wall-mount / inverter": "wall_mount",
    "Static transfer switch": "static_transfer_switch",
}
_BATTERY_MODE_KEY_MAP: dict[str, str] = {
    "Long back-up (external battery)": "external",
    "Built-in battery": "built_in",
    "Built-in battery + Long back-up (external battery)": "built_in_and_external",
    "Lithium-ion compatible": "lithium_compatible",
}
_TECHNOLOGY_KEY_MAP: dict[str, str] = {
    "Servo (electro-mechanical)": "servo",
    "Static (non-contact)": "static",
}
_PHASE_IN_OUT_PATTERN = re.compile(r"^\s*(\d)\s*-in\s*/\s*(\d)\s*-out\s*$", re.IGNORECASE)
_PHASE_WORD_TO_COUNT = {"Single phase": 1, "Three phase": 3}
_VOLTAGE_CLASS_PATTERN = re.compile(r"(\d+(?:\.\d+)?)")
_SERVICE_LIFE_YEARS_PATTERN = re.compile(r"(\d+(?:\.\d+)?)\s*years?", re.IGNORECASE)


def _is_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, float) and math.isnan(value):
        return False
    if isinstance(value, str) and not value.strip():
        return False
    try:
        return not pd.isna(value)
    except (TypeError, ValueError):
        return True


def _decimal(value: Any) -> Decimal | None:
    return Decimal(str(value)) if _is_present(value) else None


def _fmt_number(value: Any) -> str:
    decimal_value = Decimal(str(value))
    if decimal_value == decimal_value.to_integral_value():
        return str(int(decimal_value))
    return str(decimal_value)


def _add_spec(specs: list[dict[str, str]], key: str, value: Any) -> None:
    if _is_present(value):
        specs.append({"key": key, "value": str(value)})


def _parse_phase_in_out(text: Any) -> tuple[int | None, int | None]:
    if not _is_present(text):
        return None, None
    match = _PHASE_IN_OUT_PATTERN.match(str(text))
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def _build_ups_row(row: pd.Series) -> tuple[ProductIngestRecord, dict[str, Any], Decimal]:
    model_code = str(row["Model Code"])
    series = str(row["Series"])
    name = f"{row['Product Title']} — {model_code} · {series}"

    specs: list[dict[str, str]] = [{"key": "domain", "value": "i-power"}]
    _add_spec(specs, "subcategory", row.get("Sub-Category"))
    _add_spec(specs, "type", row.get("Type"))
    specs.append({"key": "model_code", "value": model_code})
    specs.append({"key": "series", "value": series})
    kva, current = row.get("Capacity (kVA)"), row.get("Current (A)")
    if _is_present(kva):
        specs.append({"key": "capacity_range", "value": f"{_fmt_number(kva)}KVA"})
    elif _is_present(current):
        specs.append({"key": "capacity_range", "value": f"{_fmt_number(current)}A"})
    _add_spec(specs, "capacity_kw", row.get("Capacity (kW)"))
    _add_spec(specs, "power_factor", row.get("Power Factor"))
    _add_spec(specs, "current_a", current)
    _add_spec(specs, "phase", row.get("Phase"))
    _add_spec(specs, "phase_in_out", row.get("Phase In/Out"))
    form_factor = row.get("Form Factor")
    _add_spec(specs, "form_factor", form_factor)
    if _is_present(form_factor) and str(form_factor) in _FORM_FACTOR_KEY_MAP:
        specs.append({"key": "form_factor_key", "value": _FORM_FACTOR_KEY_MAP[str(form_factor)]})
    battery_config = row.get("Battery Configuration")
    _add_spec(specs, "battery_configuration", battery_config)
    if _is_present(battery_config) and str(battery_config) in _BATTERY_MODE_KEY_MAP:
        specs.append({"key": "battery_mode", "value": _BATTERY_MODE_KEY_MAP[str(battery_config)]})
    _add_spec(specs, "parallel_capable", row.get("Parallel Capable"))
    _add_spec(specs, "applications", row.get("Applications"))
    _add_spec(specs, "data_quality_note", row.get("Data Quality Note"))

    phase_in, phase_out = _parse_phase_in_out(row.get("Phase In/Out"))
    typed: dict[str, Any] = {
        "capacity_kva": _decimal(kva),
        "rated_power_kw": _decimal(row.get("Capacity (kW)")),
        "power_factor": _decimal(row.get("Power Factor")),
        "current_a": _decimal(current),
        "phase_input_count": phase_in,
        "phase_output_count": phase_out,
    }

    ingest_record = ProductIngestRecord(
        name=name, brand=_BRAND, category=_UPS_CATEGORY,
        description=str(row["RAG Chunk Text"]), specs=specs,
    )
    price = _price_for_power(kva, current)
    return ingest_record, typed, price


def _build_avr_row(row: pd.Series) -> tuple[ProductIngestRecord, dict[str, Any], Decimal]:
    model_code = str(row["Model Code"])
    series = str(row["Series"])
    # The AVR sheet has no "Product Title" column (unlike UPS) — the RAG Chunk
    # Text's first line is already a well-formed title ("i-power AVR-1001 —
    # 1 kVA Servo Automatic Voltage Regulator (Single phase, 230 V class)"),
    # authored for exactly this purpose.
    title = str(row["RAG Chunk Text"]).split("\n", 1)[0].strip()
    name = f"{title} — {model_code} · {series}"

    specs: list[dict[str, str]] = [{"key": "domain", "value": "i-power"}]
    _add_spec(specs, "subcategory", row.get("Sub-Category"))
    _add_spec(specs, "product_group", row.get("Product Group"))
    specs.append({"key": "model_code", "value": model_code})
    specs.append({"key": "series", "value": series})
    technology = row.get("Technology")
    _add_spec(specs, "technology", technology)
    if _is_present(technology) and str(technology) in _TECHNOLOGY_KEY_MAP:
        specs.append({"key": "technology_key", "value": _TECHNOLOGY_KEY_MAP[str(technology)]})
    kva = row.get("Capacity (kVA)")
    if _is_present(kva):
        specs.append({"key": "capacity_range", "value": f"{_fmt_number(kva)}KVA"})
    phase = row.get("Phase")
    _add_spec(specs, "phase", phase)
    _add_spec(specs, "voltage_class", row.get("Voltage Class"))
    _add_spec(specs, "applications", row.get("Applications"))
    _add_spec(specs, "data_quality_note", row.get("Data Quality Note"))

    phase_count = _PHASE_WORD_TO_COUNT.get(str(phase)) if _is_present(phase) else None
    voltage_class_v = None
    voltage_class_text = row.get("Voltage Class")
    if _is_present(voltage_class_text):
        match = _VOLTAGE_CLASS_PATTERN.search(str(voltage_class_text))
        if match:
            voltage_class_v = Decimal(match.group(1))
    typed: dict[str, Any] = {
        "capacity_kva": _decimal(kva),
        "phase_input_count": phase_count,
        "phase_output_count": phase_count,
        "voltage_class_v": voltage_class_v,
    }

    ingest_record = ProductIngestRecord(
        name=name, brand=_BRAND, category=_AVR_CATEGORY,
        description=str(row["RAG Chunk Text"]), specs=specs,
    )
    price = _price_for_power(kva, None)
    return ingest_record, typed, price


def _build_battery_row(row: pd.Series) -> tuple[ProductIngestRecord, dict[str, Any], Decimal]:
    model_code = str(row["Model Code"])
    name = f"i-power {model_code} · {row.get('Product Group', model_code)}"

    specs: list[dict[str, str]] = [{"key": "domain", "value": "i-power"}]
    _add_spec(specs, "subcategory", row.get("Sub-Category"))
    _add_spec(specs, "product_group", row.get("Product Group"))
    specs.append({"key": "model_code", "value": model_code})
    chemistry = row.get("Chemistry")
    _add_spec(specs, "chemistry", chemistry)
    if _is_present(chemistry):
        specs.append({"key": "chemistry_key", "value": str(chemistry).lower()})
    _add_spec(specs, "nominal_voltage_vdc", row.get("Nominal Voltage (VDC)"))
    _add_spec(specs, "capacity_ah", row.get("Capacity (Ah)"))
    _add_spec(specs, "energy_kwh", row.get("Energy (kWh)"))
    _add_spec(specs, "max_discharge_power_kw", row.get("Max Discharge Power (kW)"))
    _add_spec(specs, "discharge_rate", row.get("Discharge Rate"))
    _add_spec(specs, "max_units_parallel", row.get("Max Units in Parallel"))
    service_life = row.get("Service Life")
    _add_spec(specs, "service_life", service_life)
    if _is_present(service_life):
        lowered = str(service_life).lower()
        if "calendar" in lowered:
            specs.append({"key": "service_life_type", "value": "calendar"})
        elif "design" in lowered:
            specs.append({"key": "service_life_type", "value": "design"})
    _add_spec(specs, "applications", row.get("Applications"))
    _add_spec(specs, "data_quality_note", row.get("Data Quality Note"))

    service_life_years = None
    if _is_present(service_life):
        match = _SERVICE_LIFE_YEARS_PATTERN.search(str(service_life))
        if match:
            service_life_years = Decimal(match.group(1))
    max_parallel = row.get("Max Units in Parallel")
    typed: dict[str, Any] = {
        "nominal_voltage_vdc": _decimal(row.get("Nominal Voltage (VDC)")),
        "capacity_ah": _decimal(row.get("Capacity (Ah)")),
        "energy_kwh": _decimal(row.get("Energy (kWh)")),
        "max_discharge_power_kw": _decimal(row.get("Max Discharge Power (kW)")),
        "max_parallel_units": int(max_parallel) if _is_present(max_parallel) else None,
        "service_life_years": service_life_years,
    }

    ingest_record = ProductIngestRecord(
        name=name, brand=_BRAND, category=_BATTERY_CATEGORY,
        description=str(row["RAG Chunk Text"]), specs=specs,
    )
    energy_kwh, capacity_ah = row.get("Energy (kWh)"), row.get("Capacity (Ah)")
    price = _price_for_battery(energy_kwh, capacity_ah)
    return ingest_record, typed, price


def _price_for_power(kva: Any, current_a: Any) -> Decimal:
    if _is_present(kva):
        return max(_MIN_PRICE, Decimal(str(kva)) * Decimal("120"))
    if _is_present(current_a):
        return max(_MIN_PRICE, Decimal(str(current_a)) * Decimal("15"))
    return _MIN_PRICE


def _price_for_battery(energy_kwh: Any, capacity_ah: Any) -> Decimal:
    if _is_present(energy_kwh):
        return max(_MIN_PRICE, Decimal(str(energy_kwh)) * Decimal("200"))
    if _is_present(capacity_ah):
        return max(_MIN_PRICE, Decimal(str(capacity_ah)) * Decimal("10"))
    return _MIN_PRICE


_SHEETS: tuple[tuple[str, Any], ...] = (
    ("ipower_UPS_refined.xlsx", _build_ups_row),
    ("ipower_AVR_refined.xlsx", _build_avr_row),
    ("ipower_Battery_refined.xlsx", _build_battery_row),
)


async def _run(tenant_id: UUID) -> None:
    settings = get_settings()
    initialize_database(settings)
    try:
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            ingestion = IngestionService(session, settings)
            print("Ensuring Qdrant collections exist...", flush=True)
            ingestion.ensure_collections()
            pricing_repository = ProductPricingRepository(session)

            total = 0
            for filename, row_builder in _SHEETS:
                df = pd.read_excel(_SOURCE_DIR / filename, sheet_name="RAG Chunks")
                triples = [row_builder(row) for _, row in df.iterrows()]
                print(f"[{filename}] embedding {len(triples)} products...", flush=True)
                texts = [ingest_record.description or ingest_record.name for ingest_record, _, _ in triples]
                vectors = ingestion.embedder.embed(texts)

                points: list[dict[str, Any]] = []
                for index, ((ingest_record, typed, price), vector) in enumerate(
                    zip(triples, vectors, strict=True), start=1
                ):
                    product = await ingestion.product_repository.create(
                        tenant_id=tenant_id,
                        name=ingest_record.name,
                        brand=ingest_record.brand,
                        category=ingest_record.category,
                        description=ingest_record.description,
                        specs=ingest_record.specs,
                        **typed,
                    )
                    await pricing_repository.upsert_price(
                        tenant_id=tenant_id, product_id=product.id, unit_price=price, currency="USD",
                    )
                    points.append(
                        {
                            "id": str(product.id),
                            "vector": vector,
                            "payload": {
                                "tenant_id": str(tenant_id),
                                "product_id": str(product.id),
                                "name": product.name,
                                "brand": product.brand,
                                "category": product.category,
                            },
                        }
                    )
                    if index % 20 == 0 or index == len(triples):
                        print(f"[{filename}] {index}/{len(triples)} written to Postgres", flush=True)

                ingestion.qdrant.upsert(PRODUCT_COLLECTION, points)
                print(f"[{filename}] upserted {len(points)} vectors to {PRODUCT_COLLECTION}", flush=True)
                total += len(points)

            print("Committing transaction...", flush=True)
            await session.commit()
        print(f"Total: {total} products ingested", flush=True)
    finally:
        await dispose_database()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest the refined i-power UPS/AVR/Battery spreadsheets into products_v1."
    )
    parser.add_argument("--tenant-id", required=True)
    args = parser.parse_args()
    asyncio.run(_run(UUID(args.tenant_id)))


if __name__ == "__main__":
    main()
