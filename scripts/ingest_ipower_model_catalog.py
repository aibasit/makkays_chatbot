"""Wire the `Updated Knowledge files/*.jsonl` UPS/Battery/AVR data into the
*live* retrieval path — Postgres `products`/`product_specs`/`product_pricing`
plus the `products_v1` Qdrant collection that `RetrievalService`/the
`retrieve_products` tool actually queries.

This supersedes the series-level UPS/AVR/Battery products from the earlier
`RAG Knowledge/` CSV pipeline with **model-level** rows (one per real SKU:
181 UPS + 6 Battery + 52 AVR = 239 products, replacing 34 + 10 + 12 = 56
series-level ones). Model-level granularity is what makes an *exact*
`capacity_kva == 6` match possible — a series-level row only ever had a range
(e.g. "1-10kVA"), which the existing `capacity_min`/`capacity_max` filtering
already handled reasonably; individual phase/form_factor/battery-configuration
values can't be represented on a range row at all.

The standalone `ipower_ups_v1`/`ipower_battery_v1`/`ipower_avr_v1` Qdrant
collections built earlier this session are untouched by this script — they
remain a validated, independent proof that exact-metadata-filtered vector
search works, but the live chatbot answers from `products_v1`, so that's
what this script populates.

Each product's `capacity_range` spec is a single point value (e.g. "6KVA"),
which `ProductRepository.create()` already auto-parses into
`capacity_min == capacity_max == 6` — the existing range-based capacity
filter (`capacity_min <= requirement <= capacity_max`) then behaves as an
exact match for free, no schema change needed. `phase`/`form_factor` are
plain specs, matched via the existing generic `spec_filters` EXISTS mechanism
in `ProductRepository.find_by_filters` — see `FilterExtractor`'s new phase
detection for how a message's "single phase"/"three phase" wording becomes
`spec_filters["phase"]`.

Run (inside Docker):

    docker compose run --rm --no-deps backend python -m scripts.ingest_ipower_model_catalog \
        --tenant-id $DEFAULT_TENANT_ID
"""

from __future__ import annotations

import argparse
import asyncio
import json
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from app.db.engine import dispose_database, get_sessionmaker, initialize_database
from app.dependencies import get_settings
from app.quotes.repository import ProductPricingRepository
from app.rag.ingestion import IngestionService
from app.rag.retrieval_service import PRODUCT_COLLECTION
from app.rag.schemas import ProductIngestRecord

_SOURCE_DIR = Path("Updated Knowledge files")
_BRAND = "Interconnect Solutions"
_MIN_PRICE = Decimal("150")

# filename -> internal line identifier (drives which spec-builder/pricing rule applies)
_FILES: dict[str, str] = {
    "ipower_UPS_RAG.jsonl": "ups_avr",
    "ipower_AVR_RAG.jsonl": "ups_avr",
    "ipower_Battery_RAG.jsonl": "battery",
}

_UPS_AVR_PASSTHROUGH_KEYS = (
    "type", "phase", "phase_in_out", "form_factor", "battery_configuration",
    "parallel_capable", "power_factor", "series", "technology", "voltage_class",
    "product_group", "data_quality_note",
)
_BATTERY_PASSTHROUGH_KEYS = (
    "chemistry", "product_group", "nominal_voltage_vdc", "capacity_ah",
    "energy_kwh", "max_discharge_power_kw", "max_units_parallel",
    "discharge_rate", "service_life", "data_quality_note",
)


def _read_model_records(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open(encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path.name}:{line_number}: invalid JSON — {exc}") from exc
            if record.get("metadata", {}).get("doc_type") == "model":
                records.append(record)
    return records


def _fmt_number(value: Any) -> str:
    decimal_value = Decimal(str(value))
    if decimal_value == decimal_value.to_integral_value():
        return str(int(decimal_value))
    return str(decimal_value)


def _specs_for_ups_or_avr(metadata: dict[str, Any]) -> list[dict[str, str]]:
    specs = [
        {"key": "domain", "value": "i-power"},
        {"key": "subcategory", "value": metadata.get("sub_category", "")},
        # Stored as its own exact-match spec (not just the `name` suffix) so
        # FilterExtractor's model-code detection can look this product up
        # deterministically — dense vector search alone was unreliable at
        # pinpointing one exact code among many near-identical descriptions.
        {"key": "model_code", "value": metadata["id"]},
    ]
    capacity_kva = metadata.get("capacity_kva")
    current_a = metadata.get("current_rating_a")
    if capacity_kva is not None:
        specs.append({"key": "capacity_range", "value": f"{_fmt_number(capacity_kva)}KVA"})
    elif current_a is not None:
        specs.append({"key": "capacity_range", "value": f"{_fmt_number(current_a)}A"})
    for key in _UPS_AVR_PASSTHROUGH_KEYS:
        value = metadata.get(key)
        if value not in (None, ""):
            specs.append({"key": key, "value": str(value)})
    if metadata.get("applications"):
        specs.append({"key": "applications", "value": metadata["applications"]})
    return specs


def _specs_for_battery(metadata: dict[str, Any]) -> list[dict[str, str]]:
    specs = [
        {"key": "domain", "value": "i-power"},
        {"key": "subcategory", "value": metadata.get("sub_category", "")},
        {"key": "model_code", "value": metadata["id"]},
    ]
    for key in _BATTERY_PASSTHROUGH_KEYS:
        value = metadata.get(key)
        if value not in (None, ""):
            specs.append({"key": key, "value": str(value)})
    if metadata.get("applications"):
        specs.append({"key": "applications", "value": metadata["applications"]})
    return specs


def _price_for(line: str, metadata: dict[str, Any]) -> Decimal:
    if line == "ups_avr":
        kva = metadata.get("capacity_kva")
        if kva is not None:
            return max(_MIN_PRICE, Decimal(str(kva)) * Decimal("120"))
        amps = metadata.get("current_rating_a")
        if amps is not None:
            return max(_MIN_PRICE, Decimal(str(amps)) * Decimal("15"))
        return _MIN_PRICE
    kwh = metadata.get("energy_kwh")
    if kwh is not None:
        return max(_MIN_PRICE, Decimal(str(kwh)) * Decimal("200"))
    ah = metadata.get("capacity_ah")
    if ah is not None:
        return max(_MIN_PRICE, Decimal(str(ah)) * Decimal("10"))
    return _MIN_PRICE


def _build_pair(line: str, record: dict[str, Any]) -> tuple[ProductIngestRecord, Decimal]:
    metadata = record["metadata"]
    specs = _specs_for_battery(metadata) if line == "battery" else _specs_for_ups_or_avr(metadata)
    # The JSONL `title` + model code still isn't always unique: 8 UPS model
    # codes are genuinely cross-listed under two different series (the same
    # ambiguity already surfaced once as a "Review Flag" in the UPS_Data CSVs
    # and handled for the standalone ipower_ups_v1 Qdrant collection earlier
    # this session) — e.g. OH1010T91607S appears under both T-4001 series 1
    # and series 5, with an identical title each time. Appending series_id
    # disambiguates those too. A repeated name is what earlier pushed `respond`
    # to show raw product_ids in a comparison table instead of readable names.
    series_id = metadata.get("series_id")
    suffix = f"{metadata['id']} · series {series_id}" if series_id is not None else metadata["id"]
    name = f"{record['title']} — {suffix}"
    ingest_record = ProductIngestRecord(
        name=name,
        brand=_BRAND,
        category=metadata.get("category", ""),
        description=record["text"],
        specs=specs,
    )
    return ingest_record, _price_for(line, metadata)


def _product_text(record: ProductIngestRecord) -> str:
    spec_text = " ".join(f"{spec['key']}: {spec['value']}" for spec in record.specs)
    parts = [record.name, record.brand or "", record.category or "", record.description or "", spec_text]
    return " ".join(part for part in parts if part)


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
            for filename, line in _FILES.items():
                records = _read_model_records(_SOURCE_DIR / filename)
                if not records:
                    continue
                pairs = [_build_pair(line, record) for record in records]
                print(f"[{filename}] embedding {len(pairs)} products...", flush=True)
                texts = [_product_text(ingest_record) for ingest_record, _ in pairs]
                vectors = ingestion.embedder.embed(texts)

                points: list[dict[str, Any]] = []
                for index, ((ingest_record, price), vector) in enumerate(
                    zip(pairs, vectors, strict=True), start=1
                ):
                    product = await ingestion.product_repository.create(
                        tenant_id=tenant_id,
                        name=ingest_record.name,
                        brand=ingest_record.brand,
                        category=ingest_record.category,
                        description=ingest_record.description,
                        specs=ingest_record.specs,
                    )
                    await pricing_repository.upsert_price(
                        tenant_id=tenant_id,
                        product_id=product.id,
                        unit_price=price,
                        currency="USD",
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
                    if index % 20 == 0 or index == len(pairs):
                        print(f"[{filename}] {index}/{len(pairs)} written to Postgres", flush=True)

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
        description="Ingest model-level i-power UPS/Battery/AVR data into products_v1."
    )
    parser.add_argument("--tenant-id", required=True)
    args = parser.parse_args()
    asyncio.run(_run(UUID(args.tenant_id)))


if __name__ == "__main__":
    main()
