"""Ingest the Interconnect Solutions i-Power / i-Connect product catalog from `RAG Knowledge/` CSVs.

The CSVs (`makkays_{domain}_products.csv` + `makkays_{domain}_models.csv`) are richer
than the generic JSON format `IngestionService.ingest_products` expects, so this script
builds `ProductIngestRecord`s from them directly, reusing `IngestionService` for
embedding/Qdrant/DB plumbing, and seeds a capacity-derived placeholder price for each
product (no real price list exists for this catalog yet).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import re
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from app.db.engine import dispose_database, get_sessionmaker, initialize_database
from app.dependencies import get_settings
from app.quotes.repository import ProductPricingRepository
from app.rag.ingestion import IngestionService
from app.rag.retrieval_service import PRODUCT_COLLECTION
from app.rag.schemas import ProductIngestRecord

_DOMAINS = ("ipower", "iconnect")
_PRICE_PER_KVA = Decimal("120")
_MIN_PRICE = Decimal("150")
_CAPACITY_NUMBER = re.compile(r"[0-9]+(?:\.[0-9]+)?")


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _models_by_product(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[row["product_id"]].append(row)
    return grouped


def _capacity_price(capacity_range: str) -> Decimal:
    """Placeholder price derived from the top of the capacity range (no real price list exists)."""
    numbers = [Decimal(n) for n in _CAPACITY_NUMBER.findall(capacity_range)]
    if not numbers:
        return _MIN_PRICE
    return max(_MIN_PRICE, max(numbers) * _PRICE_PER_KVA)


def _product_text(record: ProductIngestRecord) -> str:
    spec_text = " ".join(f"{spec['key']}: {spec['value']}" for spec in record.specs)
    parts = [record.name, record.brand or "", record.category or "", record.description or "", spec_text]
    return " ".join(part for part in parts if part)


def _build_records(source_dir: Path, domain: str) -> list[tuple[ProductIngestRecord, str]]:
    """Return (record, capacity_range) pairs for one domain's product CSV."""
    products = _read_csv(source_dir / f"makkays_{domain}_products.csv")
    models = _models_by_product(_read_csv(source_dir / f"makkays_{domain}_models.csv"))
    pairs: list[tuple[ProductIngestRecord, str]] = []
    for row in products:
        specs: list[dict[str, str]] = [
            {"key": "domain", "value": row["domain"]},
            {"key": "subcategory", "value": row["subcategory"]},
            {"key": "capacity_range", "value": row["capacity_range"]},
        ]
        if row["applications"]:
            specs.append({"key": "applications", "value": row["applications"]})
        for model_row in models.get(row["product_id"], []):
            if model_row["model_code"] == "(not listed in source)":
                continue
            value = model_row["capacity"]
            if model_row["variant"]:
                value = f"{value} ({model_row['variant']})"
            specs.append({"key": f"model:{model_row['model_code']}", "value": value})
        description = " ".join(filter(None, [row["short_description"], row["product_info"]]))
        record = ProductIngestRecord(
            name=row["display_name"] or row["title"],
            brand="Interconnect Solutions",
            category=row["category"],
            description=description,
            specs=specs,
        )
        pairs.append((record, row["capacity_range"]))
    return pairs


async def _run(source_dir: Path, tenant_id: UUID, domains: tuple[str, ...]) -> None:
    settings = get_settings()
    initialize_database(settings)
    try:
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            ingestion = IngestionService(session, settings)
            print("Ensuring Qdrant collections exist...", flush=True)
            ingestion.ensure_collections()
            print("Qdrant collections ready.", flush=True)
            pricing_repository = ProductPricingRepository(session)
            total = 0
            for domain in domains:
                pairs = _build_records(source_dir, domain)
                if not pairs:
                    continue
                print(f"[{domain}] embedding {len(pairs)} products...", flush=True)
                texts = [_product_text(record) for record, _ in pairs]
                vectors = ingestion.embedder.embed(texts)
                print(f"[{domain}] embeddings computed, writing to Postgres...", flush=True)
                points = []
                for index, ((record, capacity_range), vector) in enumerate(zip(pairs, vectors, strict=True), start=1):
                    product = await ingestion.product_repository.create(
                        tenant_id=tenant_id,
                        name=record.name,
                        brand=record.brand,
                        category=record.category,
                        description=record.description,
                        specs=record.specs,
                    )
                    await pricing_repository.upsert_price(
                        tenant_id=tenant_id,
                        product_id=product.id,
                        unit_price=_capacity_price(capacity_range),
                        currency="USD",
                    )
                    if index % 10 == 0 or index == len(pairs):
                        print(f"[{domain}] {index}/{len(pairs)} products written to Postgres", flush=True)
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
                print(f"[{domain}] upserting {len(points)} vectors to Qdrant...", flush=True)
                ingestion.qdrant.upsert(PRODUCT_COLLECTION, points)
                print(f"Ingested {len(pairs)} {domain} products (with placeholder pricing)", flush=True)
                total += len(pairs)
            print("Committing transaction...", flush=True)
            await session.commit()
        print(f"Total: {total} products ingested", flush=True)
    finally:
        await dispose_database()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest RAG Knowledge product CSVs with placeholder pricing.")
    parser.add_argument("--source-dir", default="RAG Knowledge")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument(
        "--domains",
        default=",".join(_DOMAINS),
        help="Comma-separated subset of domains to ingest (default: all).",
    )
    args = parser.parse_args()
    domains = tuple(d.strip() for d in args.domains.split(",") if d.strip())
    asyncio.run(_run(Path(args.source_dir), UUID(args.tenant_id), domains))


if __name__ == "__main__":
    main()
