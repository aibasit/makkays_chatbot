"""Router — sole entrypoint for turn-level intent classification (Tier 1 -> Tier 2)."""

from __future__ import annotations

from app.llm.schemas import LLMClientProtocol
from app.router.classifier import Tier2Classifier
from app.router.rules import Tier1RuleEngine
from app.session.schemas import ConversationStateSchema, FactsSchema
from app.shared.intent_context import IntentResult, PromptProvider
from app.turns.schemas import ConversationTurnRead


class Router:
    """Orchestrates the Tier 1 -> Tier 2 classification fallback."""

    def __init__(self, intent_taxonomy: tuple[str, ...]) -> None:
        self.tier1 = Tier1RuleEngine()
        self.tier2 = Tier2Classifier(intent_taxonomy)

    async def classify(
        self,
        message: str,
        facts: FactsSchema,
        state: ConversationStateSchema,
        recent_turns: list[ConversationTurnRead],
        prompt_manager: PromptProvider,
        llm_client: LLMClientProtocol,
    ) -> IntentResult:
        """Classify one turn's intent; Tier 1 short-circuits Tier 2 only when unambiguous."""
        spec_question_detected = self.tier1.detect_spec_question(message)

        tier1_result = self.tier1.match(message)
        if tier1_result is not None:
            return tier1_result.model_copy(update={"spec_question_detected": spec_question_detected})

        tier2_result = await self.tier2.classify(
            message, facts, state, recent_turns, prompt_manager, llm_client
        )
        return tier2_result.model_copy(update={"spec_question_detected": spec_question_detected})
