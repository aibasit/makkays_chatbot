"""Maps a named use case (e.g. "school") to a pre-defined requirements profile and BOM."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_config import get_logger
from app.solution_builder.bom_service import BOMService
from app.solution_builder.exceptions import UseCaseNotFoundError
from app.solution_builder.repository import UseCaseProfileRepository
from app.solution_builder.schemas import UseCaseSolution, WizardRequirements

logger = get_logger(__name__)


class UseCaseService:
    """Resolves a use case to its seeded requirements profile, then builds a BOM."""

    def __init__(
        self,
        db_session: AsyncSession,
        *,
        profile_repository: UseCaseProfileRepository | None = None,
        bom_service: BOMService | None = None,
    ) -> None:
        self.profile_repository = profile_repository or UseCaseProfileRepository(db_session)
        self.bom_service = bom_service or BOMService(db_session)

    async def recommend(self, use_case: str, tenant_id: UUID) -> UseCaseSolution:
        """Return a Solution for `use_case`, using its seeded profile if one exists."""
        profile = await self.profile_repository.get(tenant_id, use_case)
        if profile is None:
            logger.info("use_case_profile_miss", extra={"use_case": use_case, "tenant_id": str(tenant_id)})
            raise UseCaseNotFoundError(f"No use-case profile found for {use_case!r}")

        logger.info("use_case_profile_hit", extra={"use_case": use_case, "tenant_id": str(tenant_id)})
        profile_fields = {key: value for key, value in profile.requirements.items() if key != "use_case"}
        requirements = WizardRequirements(use_case=use_case, **profile_fields)
        solution = await self.bom_service.build(requirements, tenant_id)
        return UseCaseSolution(use_case=use_case, solution=solution, profile_used=True)
