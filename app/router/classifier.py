"""Tier 2 LLM-based intent classification via a bundled `classify_intent` tool call."""

from __future__ import annotations

from typing import Any

from app.llm.context import build_llm_messages
from app.llm.schemas import LLMClientProtocol, LLMResponse
from app.llm.tool_schema import build_tool_schema
from app.logging_config import get_logger
from app.router.exceptions import ClassificationFailedError
from app.session.schemas import ConversationStateSchema, FactsSchema
from app.shared.intent_context import ClassifyIntentArguments, IntentResult, PromptProvider
from app.turns.schemas import ConversationTurnRead

logger = get_logger(__name__)

CLASSIFY_INTENT_TOOL_NAME = "classify_intent"

_CLASSIFY_INTENT_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "intent": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "candidates": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["intent", "confidence"],
}

# Returned whenever classification cannot be trusted; confidence 0.0 always
# routes the turn to clarification regardless of this label (discard-on-uncertainty).
_FAILURE_FALLBACK_INTENT = "out_of_scope"


class Tier2Classifier:
    """Bundled LLM classify_intent tool call, mandatory as the turn's only tool this call."""

    def __init__(self, intent_taxonomy: tuple[str, ...]) -> None:
        self.intent_taxonomy = intent_taxonomy

    async def classify(
        self,
        message: str,
        facts: FactsSchema,
        state: ConversationStateSchema,
        recent_turns: list[ConversationTurnRead],
        prompt_manager: PromptProvider,
        llm_client: LLMClientProtocol,
    ) -> IntentResult:
        """Classify one turn's intent, never raising — failures become confidence 0.0."""
        system_prompt = prompt_manager.get("classification", "classify_intent", "1")
        messages, _metadata = build_llm_messages(
            system_prompt=system_prompt,
            facts=facts,
            state=state,
            recent_turns=recent_turns,
            latest_user_message=message,
        )
        tool_schema = build_tool_schema(
            CLASSIFY_INTENT_TOOL_NAME,
            "Classify the user's message into exactly one supported intent.",
            _CLASSIFY_INTENT_PARAMETERS,
        )

        try:
            response = await llm_client.chat(messages, tools=[tool_schema], temperature=0.0)
            arguments = self._parse_response(response)
        except Exception as exc:
            logger.warning("tier2_classification_failed", extra={"error": str(exc)})
            return IntentResult(
                intent=_FAILURE_FALLBACK_INTENT,
                confidence=0.0,
                source="tier2",
                candidates=[],
            )

        if arguments.intent not in self.intent_taxonomy:
            logger.warning("tier2_unrecognized_intent", extra={"intent": arguments.intent})
            return IntentResult(
                intent=_FAILURE_FALLBACK_INTENT,
                confidence=0.0,
                source="tier2",
                candidates=[c for c in arguments.candidates if c in self.intent_taxonomy],
            )

        confidence = self._clamp_confidence(arguments.confidence)
        candidates = [c for c in arguments.candidates if c in self.intent_taxonomy]
        logger.info(
            "intent_classified",
            extra={"tier": "tier2", "intent": arguments.intent, "confidence": confidence},
        )
        return IntentResult(
            intent=arguments.intent,
            confidence=confidence,
            source="tier2",
            candidates=candidates,
        )

    @staticmethod
    def _parse_response(response: LLMResponse) -> ClassifyIntentArguments:
        tool_call = next(
            (call for call in response.tool_calls if call.name == CLASSIFY_INTENT_TOOL_NAME),
            None,
        )
        if tool_call is None:
            raise ClassificationFailedError("Model did not call classify_intent")
        try:
            return ClassifyIntentArguments(**tool_call.arguments)
        except Exception as exc:
            raise ClassificationFailedError("classify_intent arguments were invalid") from exc

    @staticmethod
    def _clamp_confidence(value: float) -> float:
        if value < 0.0 or value > 1.0:
            logger.warning("tier2_confidence_out_of_range", extra={"confidence": value})
        return max(0.0, min(1.0, value))
