"""Local CLI for seeding product_pricing rows after product ingestion."""

from __future__ import annotations

import argparse
import asyncio
import json
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from app.db.engine import dispose_database, get_sessionmaker, initialize_database
from app.dependencies import get_settings
from app.quotes.repository import ProductPricingRepository


async def _run() -> None:
    parser = argparse.ArgumentParser(description="Seed product_pricing rows.")
    parser.add_argument("--source", required=True)
    parser.add_argument("--tenant-id", required=True)
    args = parser.parse_args()

    settings = get_settings()
    initialize_database(settings)
    try:
        tenant_id = UUID(args.tenant_id)
        records = json.loads(Path(args.source).read_text(encoding="utf-8"))
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            repository = ProductPricingRepository(session)
            for record in records:
                await repository.upsert_price(
                    tenant_id=tenant_id,
                    product_id=UUID(record["product_id"]),
                    unit_price=Decimal(str(record["unit_price"])),
                    currency=str(record.get("currency") or "USD"),
                )
            await session.commit()
        print(f"Seeded {len(records)} pricing rows")
    finally:
        await dispose_database()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
