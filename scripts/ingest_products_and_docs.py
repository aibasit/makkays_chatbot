"""Local CLI for ingesting products or documents into Postgres and Qdrant."""

from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

from app.db.engine import dispose_database, get_sessionmaker, initialize_database
from app.dependencies import get_settings
from app.rag.ingestion import IngestionService


async def _run() -> None:
    parser = argparse.ArgumentParser(description="Ingest local product/document RAG data.")
    parser.add_argument("--type", choices=["products", "docs"], default="products")
    parser.add_argument("--source", required=True)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--doc-type", default="technical_doc")
    args = parser.parse_args()

    settings = get_settings()
    initialize_database(settings)
    try:
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            service = IngestionService(session, settings)
            service.ensure_collections()
            tenant_id = UUID(args.tenant_id)
            if args.type == "products":
                count = await service.ingest_products(args.source, tenant_id)
            else:
                count = await service.ingest_documents(
                    args.source,
                    tenant_id,
                    doc_type=args.doc_type,
                )
            await session.commit()
            print(f"Ingested {count} {args.type} records")
    finally:
        await dispose_database()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
