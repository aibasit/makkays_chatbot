"""Top-level per-turn control flow."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from app.cache.redis_client import get_redis
from app.clarification.exceptions import MaxClarificationRoundsExceededError
from app.clarification.flow import ClarificationFlow
from app.db.engine import get_sessionmaker
from app.dependencies import get_settings
from app.flags.service import FeatureFlagsService
from app.language.detection_service import LanguageDetectionService
from app.language.schemas import LanguageCode
from app.language.translation_service import TranslationService
from app.llm.factory import get_llm_client
from app.llm.schemas import LLMClientProtocol
from app.logging_config import get_logger
from app.observability import registry as metrics
from app.planner.planner import TaskPlanner
from app.prompts.manager import prompt_manager
from app.router.facts_extractor import FactsExtractor
from app.router.router import Router
from app.session.schemas import ConversationStateUpdate
from app.session.service import SessionStateService
from app.shared.intent_context import IntentResult, PromptProvider
from app.solution_builder.repository import WizardSessionRepository
from app.tools.policy import policy_registry
from app.tools.schemas import SessionContext, ToolExecutionResult
from app.tools.executor import ToolExecutor
from app.turns.service import TurnsService

logger = get_logger(__name__)


class OrchestratorResult(BaseModel):
    """Public result returned to Module 15 after one completed turn."""

    assistant_message: str
    session_id: str
    intent: str | None = None
    awaiting_clarification: bool = False
    plan: list[str] = Field(default_factory=list)
    tool_calls: list[dict[str, object]] = Field(default_factory=list)


class Orchestrator:
    """Coordinates session loading, routing, planning, tools, and turn audit."""

    async def on_turn(
        self,
        tenant_id: UUID,
        session_id: str,
        message: str,
        llm_client: LLMClientProtocol | None = None,
        prompt_provider: PromptProvider | None = None,
        language_hint: LanguageCode | None = None,
    ) -> OrchestratorResult:
        """Handle one user message and return the assistant response payload."""
        settings = get_settings()
        llm = llm_client or get_llm_client(settings)
        prompts = prompt_provider or prompt_manager
        redis = get_redis()
        sessionmaker = get_sessionmaker()

        async with sessionmaker() as db_session:
            session_state = SessionStateService(db_session, redis, settings)
            turns = TurnsService(db_session)
            flags_service = FeatureFlagsService(db_session, settings)

            facts = await session_state.get_facts(tenant_id, session_id)
            state = await session_state.get_conversation_state(tenant_id, session_id)
            recent_turns = await turns.get_recent_turns(tenant_id, session_id, limit=8)
            flags = await flags_service.resolve(tenant_id)

            if flags.enable_multi_language:
                state = await _apply_language_detection(
                    session_state=session_state,
                    tenant_id=tenant_id,
                    session_id=session_id,
                    message=message,
                    state=state,
                    language_hint=language_hint,
                )

            facts_patch = await FactsExtractor().extract(
                message,
                facts,
                state,
                recent_turns,
                prompts,
                llm,
            )
            facts = await session_state.update_facts(tenant_id, session_id, facts_patch)

            # An in-progress wizard (Module 19) owns every turn until it completes —
            # without this, a follow-up answer like "200 devices" would get
            # reclassified from scratch and the wizard would silently stall after
            # its first question, since nothing else would route back to it.
            active_wizard = (
                await WizardSessionRepository(db_session).get_active(tenant_id, session_id)
                if flags.enable_wizard
                else None
            )
            if active_wizard is not None:
                intent_result = IntentResult(
                    intent="product_recommendation_wizard",
                    confidence=1.0,
                    source="tier1",
                    candidates=["product_recommendation_wizard"],
                )
            else:
                intent_result = await Router(settings.router.intent_taxonomy).classify(
                    message,
                    facts,
                    state,
                    recent_turns,
                    prompts,
                    llm,
                )
            metrics.metrics_registry.increment_intent_classification(
                source=intent_result.source,
                intent=intent_result.intent,
            )
            metrics.metrics_registry.record_intent_confidence(intent_result.confidence)
            state = await session_state.update_conversation_state(
                tenant_id,
                session_id,
                ConversationStateUpdate(
                    current_intent=intent_result.intent,
                    intent_confidence=intent_result.confidence,
                    spec_question_detected=intent_result.spec_question_detected,
                    contact_info_captured=bool(facts.contact_email or facts.contact_phone),
                ),
            )
            turn_number = await turns.get_next_turn_number(tenant_id, session_id)

            if intent_result.confidence < settings.router.classification_confidence_threshold:
                try:
                    clarification = await ClarificationFlow(session_state, settings).run(
                        tenant_id,
                        session_id,
                        intent_result,
                        facts,
                        state,
                        flags,
                        prompts,
                        llm,
                    )
                    assistant_message = await _maybe_translate_response(
                        clarification.question_text,
                        state.language_code,
                        flags.enable_multi_language,
                        llm,
                        prompts,
                    )
                    await turns.record_turn(
                        tenant_id,
                        session_id,
                        turn_number,
                        message,
                        assistant_message=assistant_message,
                        intent_result=_intent_payload(intent_result),
                    )
                    await db_session.commit()
                    return OrchestratorResult(
                        assistant_message=assistant_message,
                        session_id=session_id,
                        intent=intent_result.intent,
                        awaiting_clarification=True,
                    )
                except MaxClarificationRoundsExceededError:
                    logger.warning("clarification_exhausted_escalating", extra={"session_id": session_id})
                    intent_result = IntentResult(
                        intent="escalation_request",
                        confidence=1.0,
                        source="tier1",
                        candidates=["escalation_request"],
                    )

            planner = TaskPlanner()
            plan = planner.build_plan(intent_result, facts, state, flags)
            state = await session_state.update_conversation_state(
                tenant_id,
                session_id,
                ConversationStateUpdate(
                    awaiting_clarification=False,
                    clarification_candidates=[],
                    current_plan=plan.model_dump(),
                    current_plan_step=0,
                ),
            )
            session_context = SessionContext(
                tenant_id=tenant_id,
                session_id=session_id,
                facts=facts,
                conversation_state=state,
                message=message,
                recent_turns=tuple(recent_turns),
            )
            executor = ToolExecutor(db_session, policy_registry)
            results = await executor.execute_plan(plan, session_context, flags)
            assistant_message = _assistant_message_from_results(results)
            assistant_message = await _maybe_translate_response(
                assistant_message,
                state.language_code,
                flags.enable_multi_language,
                llm,
                prompts,
            )
            tool_calls = [_tool_call_record(result) for result in results]

            await turns.record_turn(
                tenant_id,
                session_id,
                turn_number,
                message,
                assistant_message=assistant_message,
                intent_result=_intent_payload(intent_result),
                tool_calls=tool_calls,
            )
            await db_session.commit()
            return OrchestratorResult(
                assistant_message=assistant_message,
                session_id=session_id,
                intent=intent_result.intent,
                awaiting_clarification=False,
                plan=plan.steps,
                tool_calls=tool_calls,
            )


def _tool_call_record(result: ToolExecutionResult) -> dict[str, object]:
    """Shape a `ToolExecutionResult` into the `{tool, args, result_summary}` audit form."""
    return {
        "tool": result.step,
        "args": {},
        "result_summary": result.result_summary,
        "success": result.success,
        "error": result.error,
        "product_ids": [str(product_id) for product_id in result.product_ids] if result.product_ids else None,
    }


def _assistant_message_from_results(results: list[ToolExecutionResult]) -> str:
    for result in reversed(results):
        if result.step == "respond" and result.success and result.result_summary:
            return result.result_summary
    for result in reversed(results):
        if result.success and result.result_summary:
            return result.result_summary
    return "I could not complete that request just now. Please try again with a little more detail."


def _intent_payload(intent_result: IntentResult) -> dict[str, object]:
    payload = intent_result.model_dump()
    payload["candidate_intents"] = intent_result.candidates
    return payload


async def _apply_language_detection(
    *,
    session_state: SessionStateService,
    tenant_id: UUID,
    session_id: str,
    message: str,
    state: object,
    language_hint: LanguageCode | None,
) -> object:
    current_language = getattr(state, "language_code", "en")
    if language_hint is not None and current_language == "en" and not getattr(state, "language_override", False):
        state = await session_state.update_conversation_state(
            tenant_id,
            session_id,
            ConversationStateUpdate(language_code=language_hint),
        )
        current_language = language_hint

    if getattr(state, "language_override", False):
        return state

    detected_language = LanguageDetectionService().detect(message, current_language)  # type: ignore[arg-type]
    metrics.metrics_registry.increment_language_detection(detected_language)
    if detected_language != current_language:
        state = await session_state.update_conversation_state(
            tenant_id,
            session_id,
            ConversationStateUpdate(language_code=detected_language),
        )
    return state


async def _maybe_translate_response(
    assistant_message: str,
    language_code: str,
    enabled: bool,
    llm_client: LLMClientProtocol,
    prompt_provider: PromptProvider,
) -> str:
    if not enabled or language_code == "en":
        return assistant_message
    if language_code not in {"ur", "ar"}:
        return assistant_message
    return await TranslationService().translate(
        assistant_message,
        language_code,  # type: ignore[arg-type]
        llm_client,
        prompt_provider,
    )
