"""TaskPlanner — deterministic step planner sitting between Router and Tool Executor."""

from __future__ import annotations

from app.flags.schemas import FeatureFlags
from app.logging_config import get_logger
from app.planner.exceptions import UnknownIntentError
from app.planner.rules import RULE_REGISTRY
from app.planner.schemas import Plan
from app.session.schemas import ConversationStateSchema, FactsSchema
from app.shared.intent_context import IntentResult

logger = get_logger(__name__)

# Authoritative registered step set (Module 00 section 16). `create_ticket` is
# reserved for a future ticket module and must never be emitted here.
REGISTERED_STEPS = frozenset(
    {
        "retrieve_products",
        "retrieve_docs",
        "compare",
        "generate_quote",
        "request_missing_slots",
        "create_lead",
        "respond",
    }
)

_FLAG_GATED_STEPS: dict[str, str] = {
    "retrieve_products": "enable_rag",
    "retrieve_docs": "enable_rag",
    "generate_quote": "enable_quotes",
    "request_missing_slots": "enable_quotes",
    "create_lead": "enable_crm",
}


class TaskPlanner:
    """Pure, deterministic per-intent plan builder. No I/O, no LLM calls."""

    def build_plan(
        self,
        intent_result: IntentResult,
        facts: FactsSchema,
        state: ConversationStateSchema,
        flags: FeatureFlags,
    ) -> Plan:
        """Look up and run the rule function registered for `intent_result.intent`."""
        rule_fn = RULE_REGISTRY.get(intent_result.intent)
        if rule_fn is None:
            logger.error("planner_unknown_intent", extra={"intent": intent_result.intent})
            raise UnknownIntentError(f"No rule function registered for intent {intent_result.intent!r}")

        steps = rule_fn(facts, state, flags, intent_result)
        if not steps:
            logger.error("planner_empty_plan", extra={"intent": intent_result.intent})
            steps = ["respond"]

        filtered_steps = self._filter_by_flags(steps, flags)
        unregistered = [step for step in filtered_steps if step not in REGISTERED_STEPS]
        if unregistered:
            logger.error(
                "planner_unregistered_step",
                extra={"intent": intent_result.intent, "steps": unregistered},
            )

        logger.debug(
            "planner_plan_built",
            extra={"intent": intent_result.intent, "steps": filtered_steps},
        )
        return Plan(intent=intent_result.intent, steps=filtered_steps)

    @staticmethod
    def _filter_by_flags(steps: list[str], flags: FeatureFlags) -> list[str]:
        """Drop steps whose owning feature flag is off (defense in depth)."""
        filtered = []
        for step in steps:
            flag_name = _FLAG_GATED_STEPS.get(step)
            if flag_name is None or getattr(flags, flag_name):
                filtered.append(step)
        return filtered or ["respond"]
