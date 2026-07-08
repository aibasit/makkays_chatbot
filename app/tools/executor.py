"""ToolExecutor — plan-constrained execution loop, plus the three built-in tools.

Module 10 executes only the deterministic `Plan.steps` emitted by Module 07's
Task Planner. The LLM never decides which business tools run.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis_client import get_redis
from app.dependencies import get_settings
from app.flags.schemas import FeatureFlags
from app.llm.context import build_llm_messages
from app.llm.factory import get_llm_client
from app.logging_config import get_logger
from app.observability import registry as metrics
from app.planner.schemas import Plan
from app.prompts.manager import prompt_manager
from app.tools.exceptions import PlanViolationError
from app.tools.policy import PolicyRegistry
from app.tools.registry import tool_registry
from app.tools.repository import ToolAuditLogRepository
from app.tools.schemas import ExecutionContext, SessionContext, ToolExecutionResult

logger = get_logger(__name__)

# If a critical step is denied by policy or throws, abort the remaining plan;
# non-critical step failures are logged but the plan continues.
CRITICAL_STEPS: frozenset[str] = frozenset({"generate_quote", "create_lead"})

# The specific Facts fields `quote_slots_complete` requires (app.quotes.schemas) —
# used only to phrase the deterministic missing-slots message below.
_QUOTE_SLOT_FIELDS: tuple[str, ...] = ("company", "product_interest", "quantity", "budget")


class ToolExecutor:
    """Executes only the steps present in the current deterministic plan."""

    def __init__(self, db_session: AsyncSession, policy_registry: PolicyRegistry) -> None:
        self.audit_repo = ToolAuditLogRepository(db_session)
        self.policy_registry = policy_registry

    async def execute_plan(
        self,
        plan: Plan,
        session: SessionContext,
        flags: FeatureFlags,
    ) -> list[ToolExecutionResult]:
        """Run each plan step in order: plan-conformance, then policy, then execution."""
        context = ExecutionContext()
        results: list[ToolExecutionResult] = []
        for step in plan.steps:
            result = await self.execute_step(step, plan, session, flags, context)
            if result is None:
                continue
            results.append(result)
            if not result.success and step in CRITICAL_STEPS:
                logger.error("critical_step_failed_aborting_plan", extra={"step": step})
                break
        return results

    async def execute_step(
        self,
        step: str,
        plan: Plan,
        session: SessionContext,
        flags: FeatureFlags,
        context: ExecutionContext | None = None,
    ) -> ToolExecutionResult | None:
        """Run one step. Returns None only for a registration/policy config bug (logged, skipped)."""
        if step not in plan.steps:
            logger.error("plan_violation", extra={"step": step, "plan_steps": plan.steps})
            raise PlanViolationError(f"Step {step!r} is not present in the current plan")

        context = context if context is not None else ExecutionContext()

        tool_fn = tool_registry.get(step, flags)
        if tool_fn is None:
            logger.error("tool_not_registered", extra={"step": step})
            return None

        policy = self.policy_registry.get(step)
        if policy is None:
            logger.error("tool_missing_policy", extra={"step": step})
            return None

        redis = get_redis()
        check = await policy.check(
            intent=plan.intent,
            state=session.conversation_state,
            facts=session.facts,
            tenant_id=session.tenant_id,
            session_id=session.session_id,
            redis=redis,
        )
        if not check.allowed:
            logger.warning(
                "tool_policy_denied",
                extra={"step": step, "clause_failed": check.clause_failed, "reason": check.reason},
            )
            if policy.audit_log:
                await self._write_audit_entry(session, step, plan.intent, allowed=False, reason=check.reason)
            denied = ToolExecutionResult(step=step, success=False, result_summary="", error=check.reason)
            metrics.metrics_registry.increment_tool_result(step, False)
            return denied

        try:
            tool_result = await tool_fn(session, context)
        except Exception as exc:
            logger.error("tool_execution_failed", extra={"step": step, "error": str(exc)})
            tool_result = ToolExecutionResult(step=step, success=False, result_summary="", error=str(exc))

        if step in ExecutionContext.model_fields:
            setattr(context, step, tool_result)

        metrics.metrics_registry.increment_tool_result(step, tool_result.success)

        if policy.audit_log:
            await self._write_audit_entry(
                session, step, plan.intent, allowed=tool_result.success, reason=tool_result.error
            )

        return tool_result

    async def _write_audit_entry(
        self,
        session: SessionContext,
        step: str,
        intent: str,
        *,
        allowed: bool,
        reason: str | None,
    ) -> None:
        try:
            await self.audit_repo.create(
                tenant_id=session.tenant_id,
                session_id=session.session_id,
                tool_name=step,
                intent=intent,
                allowed=allowed,
                denial_reason=reason,
            )
        except Exception as exc:
            logger.error("tool_audit_log_write_failed", extra={"step": step, "error": str(exc)})


async def _respond_tool(session: SessionContext, context: ExecutionContext) -> ToolExecutionResult:
    """Compose the final assistant message via the configured LLM provider."""
    if context.generate_quote and context.generate_quote.success:
        return ToolExecutionResult(
            step="respond",
            success=True,
            result_summary=context.generate_quote.result_summary,
        )

    settings = get_settings()
    llm_client = get_llm_client(settings)
    system_prompt = prompt_manager.get("system", "base", "1")
    messages, _metadata = build_llm_messages(
        system_prompt=system_prompt,
        facts=session.facts,
        state=session.conversation_state,
    )
    try:
        response = await llm_client.chat(messages)
    except Exception as exc:
        return ToolExecutionResult(step="respond", success=False, result_summary="", error=str(exc))
    return ToolExecutionResult(step="respond", success=True, result_summary=response.content or "")


async def _compare_tool(session: SessionContext, context: ExecutionContext) -> ToolExecutionResult:
    """Format a comparison summary from products surfaced by `retrieve_products`.

    Module 11 (RAG Engine) will supply real product detail dicts once built; until
    then this can only report how many candidate products are available to compare.
    """
    product_ids = context.get_product_ids()
    if not product_ids:
        return ToolExecutionResult(
            step="compare", success=False, result_summary="", error="No retrieved products to compare"
        )
    summary = f"Found {len(product_ids)} candidate products to compare."
    return ToolExecutionResult(step="compare", success=True, result_summary=summary, product_ids=product_ids)


async def _request_missing_slots_tool(
    session: SessionContext, context: ExecutionContext
) -> ToolExecutionResult:
    """Ask for whichever quote-relevant facts are still missing.

    Module 13 (Clarification Template Library) will own real templated copy via
    `TemplateLookup`; until it exists this builds a plain, deterministic message.
    """
    missing = [field for field in _QUOTE_SLOT_FIELDS if getattr(session.facts, field, None) is None]
    if not missing:
        summary = "All the details needed for a quote are already on file."
    else:
        pretty = ", ".join(field.replace("_", " ") for field in missing)
        summary = f"To put together a quote, could you share your {pretty}?"
    return ToolExecutionResult(step="request_missing_slots", success=True, result_summary=summary)


# Built-in tools register themselves at module load time, per Module 00 section 16.
tool_registry.register("respond", _respond_tool)
tool_registry.register("compare", _compare_tool)
tool_registry.register("request_missing_slots", _request_missing_slots_tool, flag_name="enable_quotes")
