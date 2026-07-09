"""Multi-turn requirement-collection wizard.

Budget is never asked: for small/medium projects the `product_pricing` table is
the authoritative price source; for large/enterprise projects catalogue pricing
can't reflect volume discounts or custom SLAs, so the wizard routes to sales
instead of presenting a misleading flat total.
"""

from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.llm.schemas import LLMClientProtocol
from app.logging_config import get_logger
from app.solution_builder.bom_service import BOMService, ScaleClassifier
from app.solution_builder.call_for_pricing_service import CallForPricingService
from app.solution_builder.exceptions import WizardAlreadyCompleteError
from app.solution_builder.repository import SolutionRepository, WizardSessionRepository
from app.solution_builder.schemas import WizardRequirements, WizardStep
from app.solution_builder.solution_explainer import SolutionExplainer
from app.tools.schemas import SessionContext

logger = get_logger(__name__)

# Step numbers matching Module 19 section 8's fixed order. Step 3 (project_size)
# is auto-classified after step 2 — no question is ever shown for it.
STEP_USE_CASE = 1
STEP_DEVICE_COUNT = 2
STEP_LOCATION = 4
STEP_BRAND_PREFERENCE = 5

_QUESTIONS: dict[int, str] = {
    STEP_USE_CASE: "What is the primary use case? (networking / power / surveillance / mixed)",
    STEP_DEVICE_COUNT: "How many devices or users need to be supported?",
    STEP_LOCATION: "What is your location or preferred delivery region?",
    STEP_BRAND_PREFERENCE: "Do you have a preferred brand? (optional — press Enter to skip)",
}

_DIGITS_PATTERN = re.compile(r"\d+")


class WizardService:
    """Advances the 5-step wizard by exactly one step per call."""

    def __init__(
        self,
        db_session: AsyncSession,
        settings: Settings,
        llm_client: LLMClientProtocol,
        *,
        repository: WizardSessionRepository | None = None,
        scale_classifier: ScaleClassifier | None = None,
        bom_service: BOMService | None = None,
        call_for_pricing_service: CallForPricingService | None = None,
        solution_explainer: SolutionExplainer | None = None,
        solution_repository: SolutionRepository | None = None,
    ) -> None:
        self.repository = repository or WizardSessionRepository(db_session)
        self.scale_classifier = scale_classifier or ScaleClassifier(settings)
        self.bom_service = bom_service or BOMService(db_session)
        self.call_for_pricing_service = call_for_pricing_service or CallForPricingService(db_session)
        self.solution_explainer = solution_explainer or SolutionExplainer()
        self.solution_repository = solution_repository or SolutionRepository(db_session)
        self.llm_client = llm_client

    async def advance(self, session: SessionContext) -> WizardStep:
        """Record this turn's answer (if any) and return the next question or the outcome."""
        tenant_id, session_id, user_message = session.tenant_id, session.session_id, session.message
        wizard_session = await self.repository.get_latest(tenant_id, session_id)

        if wizard_session is not None and wizard_session.completed:
            raise WizardAlreadyCompleteError(f"Wizard session {session_id!r} is already complete")

        if wizard_session is None:
            await self.repository.upsert(tenant_id, session_id, step=STEP_USE_CASE, requirements={}, completed=False)
            logger.info(
                "wizard_step_advanced",
                extra={"session_id": session_id, "step_number": STEP_USE_CASE, "is_complete": False},
            )
            return WizardStep(step_number=STEP_USE_CASE, question_text=_QUESTIONS[STEP_USE_CASE], is_complete=False)

        requirements = dict(wizard_session.collected_requirements)
        current_step = wizard_session.current_step
        answer = user_message.strip()

        if current_step == STEP_USE_CASE:
            requirements["use_case"] = answer or None
            next_step: int | None = STEP_DEVICE_COUNT
        elif current_step == STEP_DEVICE_COUNT:
            requirements["device_count"] = _parse_device_count(answer)
            next_step = STEP_LOCATION
        elif current_step == STEP_LOCATION:
            requirements["location"] = answer or None
            next_step = STEP_BRAND_PREFERENCE
        elif current_step == STEP_BRAND_PREFERENCE:
            requirements["brand_preference"] = answer or None
            next_step = None
        else:
            logger.error("wizard_unexpected_step", extra={"session_id": session_id, "current_step": current_step})
            next_step = None

        if next_step is not None:
            await self.repository.upsert(
                tenant_id, session_id, step=next_step, requirements=requirements, completed=False
            )
            logger.info(
                "wizard_step_advanced",
                extra={"session_id": session_id, "step_number": next_step, "is_complete": False},
            )
            return WizardStep(step_number=next_step, question_text=_QUESTIONS.get(next_step), is_complete=False)

        return await self._complete(tenant_id, session_id, requirements)

    async def _complete(self, tenant_id: UUID, session_id: str, requirements: dict) -> WizardStep:
        wizard_requirements = WizardRequirements(
            use_case=requirements.get("use_case"),
            device_count=requirements.get("device_count"),
            location=requirements.get("location"),
            brand_preference=requirements.get("brand_preference"),
        )
        scale = self.scale_classifier.classify(wizard_requirements.device_count or 0, wizard_requirements.use_case)
        wizard_requirements.project_size = scale
        requirements["project_size"] = scale.model_dump()

        await self.repository.upsert(
            tenant_id, session_id, step=STEP_BRAND_PREFERENCE, requirements=requirements, completed=True
        )
        logger.info(
            "wizard_step_advanced",
            extra={"session_id": session_id, "step_number": STEP_BRAND_PREFERENCE, "is_complete": True},
        )

        if scale.pricing_mode == "call_for_pricing":
            result = await self.call_for_pricing_service.handle(wizard_requirements, scale, tenant_id, session_id)
            return WizardStep(step_number=STEP_BRAND_PREFERENCE, is_complete=True, call_for_pricing=result)

        solution = await self.bom_service.build(wizard_requirements, tenant_id)
        solution.narration = await self.solution_explainer.explain(solution, self.llm_client)
        saved = await self.solution_repository.create(tenant_id, session_id, solution)
        return WizardStep(step_number=STEP_BRAND_PREFERENCE, is_complete=True, solution=saved)


def _parse_device_count(answer: str) -> int | None:
    match = _DIGITS_PATTERN.search(answer)
    return int(match.group(0)) if match else None
