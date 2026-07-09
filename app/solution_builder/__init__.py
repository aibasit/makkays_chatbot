"""Solution Builder & Recommendation Wizard (Module 19) and Tool Executor registration.

Product discovery (Module 11) answers "what product fits this query." This
module answers "what complete set of products solves this deployment
problem." BOM generation keeps pricing deterministic: the LLM never computes
quantities or prices, only narrates the pre-computed solution.
"""

from __future__ import annotations

from app.db.engine import get_sessionmaker
from app.dependencies import get_settings
from app.llm.factory import get_llm_client
from app.logging_config import get_logger
from app.solution_builder.bom_service import BOMService
from app.solution_builder.exceptions import (
    InsufficientProductDataError,
    UseCaseNotFoundError,
    WizardAlreadyCompleteError,
)
from app.solution_builder.repository import SolutionRepository
from app.solution_builder.schemas import Solution, WizardRequirements, WizardStep
from app.solution_builder.solution_explainer import SolutionExplainer
from app.solution_builder.use_case_service import UseCaseService
from app.solution_builder.wizard_service import WizardService
from app.tools.registry import tool_registry
from app.tools.schemas import ExecutionContext, SessionContext, ToolExecutionResult

logger = get_logger(__name__)

__all__ = ["BOMService", "SolutionExplainer", "UseCaseService", "WizardService"]


async def run_wizard_tool(session: SessionContext, context: ExecutionContext) -> ToolExecutionResult:
    """Advance the multi-turn wizard by one step for this turn's message."""
    settings = get_settings()
    llm_client = get_llm_client(settings)
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db_session:
        service = WizardService(db_session, settings, llm_client)
        try:
            step = await service.advance(session)
        except WizardAlreadyCompleteError:
            return ToolExecutionResult(
                step="run_wizard",
                success=True,
                result_summary="Your solution request has already been completed for this session.",
            )
        await db_session.commit()

    return ToolExecutionResult(step="run_wizard", success=True, result_summary=_format_wizard_step(step))


async def build_use_case_solution_tool(session: SessionContext, context: ExecutionContext) -> ToolExecutionResult:
    """Build a solution from a seeded use-case profile (e.g. "school", "hospital")."""
    use_case = session.facts.product_interest or ""
    if not use_case:
        return ToolExecutionResult(
            step="build_use_case_solution", success=False, result_summary="", error="No use case identified"
        )

    settings = get_settings()
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db_session:
        service = UseCaseService(db_session)
        try:
            result = await service.recommend(use_case, session.tenant_id)
        except UseCaseNotFoundError:
            return ToolExecutionResult(
                step="build_use_case_solution",
                success=False,
                result_summary="",
                error=f"No profile found for use case {use_case!r}",
            )
        except InsufficientProductDataError as exc:
            return ToolExecutionResult(step="build_use_case_solution", success=False, result_summary="", error=str(exc))

        llm_client = get_llm_client(settings)
        result.solution.narration = await SolutionExplainer().explain(result.solution, llm_client)
        await db_session.commit()

    return ToolExecutionResult(
        step="build_use_case_solution", success=True, result_summary=_format_solution(result.solution)
    )


async def build_solution_tool(session: SessionContext, context: ExecutionContext) -> ToolExecutionResult:
    """Build a solution directly from already-known facts, without the guided wizard."""
    requirements = WizardRequirements(
        use_case=session.facts.product_interest,
        device_count=session.facts.quantity,
    )
    settings = get_settings()
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db_session:
        bom_service = BOMService(db_session)
        try:
            solution = await bom_service.build(requirements, session.tenant_id)
        except InsufficientProductDataError as exc:
            return ToolExecutionResult(step="build_solution", success=False, result_summary="", error=str(exc))

        llm_client = get_llm_client(settings)
        solution.narration = await SolutionExplainer().explain(solution, llm_client)
        saved = await SolutionRepository(db_session).create(session.tenant_id, session.session_id, solution)
        await db_session.commit()

    return ToolExecutionResult(step="build_solution", success=True, result_summary=_format_solution(saved))


def _format_wizard_step(step: WizardStep) -> str:
    if not step.is_complete:
        return step.question_text or ""
    if step.call_for_pricing is not None:
        return step.call_for_pricing.message
    if step.solution is not None:
        return _format_solution(step.solution)
    return "Your requirements have been recorded."


def _format_solution(solution: Solution) -> str:
    return solution.narration


tool_registry.register("run_wizard", run_wizard_tool, flag_name="enable_wizard")
tool_registry.register(
    "build_use_case_solution", build_use_case_solution_tool, flag_name="enable_use_case_recommendation"
)
tool_registry.register("build_solution", build_solution_tool, flag_name="enable_solution_builder")
