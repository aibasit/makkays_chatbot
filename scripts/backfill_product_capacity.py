"""Backfill structured capacity_min/max/unit for already-ingested products.

`ProductRepository.create()` now derives these automatically from a
`capacity_range` spec at ingestion time, but that only applies to products
created after that change. This script re-parses the existing `capacity_range`
spec row for every already-ingested product and fills in the new columns
in place — no re-ingestion (and no re-embedding) required.
"""

from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

from sqlalchemy import select

from app.db.engine import dispose_database, get_sessionmaker, initialize_database
from app.dependencies import get_settings
from app.rag.capacity import parse_capacity_range
from app.rag.models import Product, ProductSpec


async def _run(tenant_id: UUID) -> None:
    settings = get_settings()
    initialize_database(settings)
    try:
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            capacity_rows = await session.execute(
                select(ProductSpec.product_id, ProductSpec.spec_value).where(
                    ProductSpec.tenant_id == tenant_id,
                    ProductSpec.spec_key == "capacity_range",
                )
            )
            capacity_by_product = {row.product_id: row.spec_value for row in capacity_rows.all()}

            products = (
                await session.execute(select(Product).where(Product.tenant_id == tenant_id))
            ).scalars().all()

            updated = 0
            skipped = 0
            for product in products:
                raw_value = capacity_by_product.get(product.id)
                parsed = parse_capacity_range(raw_value)
                if parsed is None:
                    skipped += 1
                    continue
                product.capacity_min = parsed.min_value
                product.capacity_max = parsed.max_value
                product.capacity_unit = parsed.unit
                updated += 1

            await session.commit()
        print(f"Backfilled capacity for {updated} products; {skipped} had no parseable capacity_range")
    finally:
        await dispose_database()


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill structured product capacity columns.")
    parser.add_argument("--tenant-id", required=True)
    args = parser.parse_args()
    asyncio.run(_run(UUID(args.tenant_id)))


if __name__ == "__main__":
    main()
