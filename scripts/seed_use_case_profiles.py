"""Local CLI for seeding the 7 default use-case profiles (Module 19).

Device counts are kept modest (under the large/enterprise scale thresholds)
even for the "enterprise"/"data_center" profiles so `BOMService.build` always
has a sensible deterministic BOM to compute — `UseCaseService.recommend` calls
`BOMService.build` directly with no call-for-pricing branch of its own.
"""

from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

from app.db.engine import dispose_database, get_sessionmaker, initialize_database
from app.dependencies import get_settings
from app.solution_builder.repository import UseCaseProfileRepository

DEFAULT_PROFILES: dict[str, dict[str, object]] = {
    "school": {"device_count": 150, "location": None, "brand_preference": None},
    "hospital": {"device_count": 200, "location": None, "brand_preference": None},
    "office": {"device_count": 60, "location": None, "brand_preference": None},
    "data_center": {"device_count": 80, "location": None, "brand_preference": None},
    "cctv": {"device_count": 40, "location": None, "brand_preference": None},
    "enterprise": {"device_count": 90, "location": None, "brand_preference": None},
    "smb": {"device_count": 30, "location": None, "brand_preference": None},
}


async def _run() -> None:
    parser = argparse.ArgumentParser(description="Seed the 7 default use-case profiles.")
    parser.add_argument("--tenant-id", required=True)
    args = parser.parse_args()

    settings = get_settings()
    initialize_database(settings)
    try:
        tenant_id = UUID(args.tenant_id)
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            repository = UseCaseProfileRepository(session)
            for use_case, requirements in DEFAULT_PROFILES.items():
                await repository.upsert(tenant_id, use_case, requirements)
            await session.commit()
        print(f"Seeded {len(DEFAULT_PROFILES)} use-case profiles")
    finally:
        await dispose_database()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
