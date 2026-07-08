"""Template-first clarification flow with optional constrained LLM rewrite."""

from __future__ import annotations

import re
from typing import Protocol
from uuid import UUID

from app.clarification.exceptions import MaxClarificationRoundsExceededError
from app.clarification.schemas import ClarificationResult
from app.clarification.template_lookup import GENERIC_FALLBACK_TEMPLATE, TemplateLookup
from app.config import Settings
from app.flags.schemas import FeatureFlags
from app.llm.context import build_llm_messages
from app.llm.schemas import LLMClientProtocol
from app.logging_config import get_logger
from app.prompts.exceptions import PromptNotFoundError
from app.session.schemas import ConversationStateSchema, FactsSchema
from app.session.service import SessionStateService
from app.shared.intent_context import IntentResult, PromptProvider

logger = get_logger(__name__)

_OPTION_LINE_PATTERN = re.compile(r"^\s*(?:[-*]\s+|\d+\.\s+)(.+?)\s*$")


class SupportsUpdateClarificationState(Protocol):
    """Small protocol for the one SessionStateService method this flow needs."""

    async def update_clarification_state(
        self,
        tenant_id: UUID,
        session_id: str,
        *,
        candidates: list[str] | None = None,
        last_question: str | None = None,
    ) -> ConversationStateSchema:
        """Persist clarification metadata and increment rounds."""
        ...


class ClarificationFlow:
    """Runs low-confidence clarification: template lookup, optional rewrite, persistence."""

    def __init__(
        self,
        session_state_service: SupportsUpdateClarificationState,
        settings: Settings,
        *,
        template_lookup: TemplateLookup | None = None,
    ) -> None:
        self.session_state_service = session_state_service
        self.settings = settings
        self.template_lookup = template_lookup or TemplateLookup()

    async def run(
        self,
        tenant_id: UUID,
        session_id: str,
        intent_result: IntentResult,
        facts: FactsSchema,
        state: ConversationStateSchema,
        flags: FeatureFlags,
        prompt_provider: PromptProvider,
        llm_client: LLMClientProtocol | None = None,
    ) -> ClarificationResult:
        """Return a clarification question and persist clarification state."""
        if state.clarification_rounds >= self.settings.clarification.max_rounds:
            logger.warning(
                "clarification_max_rounds_exceeded",
                extra={"session_id": session_id, "rounds": state.clarification_rounds},
            )
            raise MaxClarificationRoundsExceededError(session_id, state.clarification_rounds)

        candidates = _candidate_list(intent_result)
        template_name = self.template_lookup.resolve(candidates)
        template_text = self._load_template(prompt_provider, template_name)
        rewrite_used = False
        question_text = template_text
        if flags.enable_llm_clarification_rewrite and llm_client is not None:
            rewritten = await self._rewrite_template(
                template_text,
                facts,
                state,
                prompt_provider,
                llm_client,
            )
            if rewritten is not None:
                question_text = rewritten
                rewrite_used = True

        updated_state = await self.session_state_service.update_clarification_state(
            tenant_id,
            session_id,
            candidates=candidates,
            last_question=question_text,
        )
        logger.info(
            "clarification_question_selected",
            extra={
                "session_id": session_id,
                "candidates": candidates,
                "template_name": template_name,
                "rewrite_used": rewrite_used,
                "round_number": updated_state.clarification_rounds,
            },
        )
        return ClarificationResult(
            question_text=question_text,
            source="template+llm_rewrite" if rewrite_used else "template",
            candidates=candidates,
            template_name=template_name,
            clarification_rounds=updated_state.clarification_rounds,
        )

    def _load_template(self, prompt_provider: PromptProvider, template_name: str) -> str:
        try:
            return prompt_provider.get("clarification", template_name, "1")
        except PromptNotFoundError:
            if template_name == GENERIC_FALLBACK_TEMPLATE:
                raise
            logger.warning(
                "clarification_template_missing_fallback",
                extra={"template_name": template_name},
            )
            return prompt_provider.get("clarification", GENERIC_FALLBACK_TEMPLATE, "1")

    async def _rewrite_template(
        self,
        template_text: str,
        facts: FactsSchema,
        state: ConversationStateSchema,
        prompt_provider: PromptProvider,
        llm_client: LLMClientProtocol,
    ) -> str | None:
        try:
            system_prompt = prompt_provider.get("clarification", "llm_rewrite_instructions", "1")
            messages, _metadata = build_llm_messages(
                system_prompt=system_prompt,
                facts=facts,
                state=state,
                latest_user_message=template_text,
                max_context_chars=4000,
            )
            response = await llm_client.chat(messages=messages, temperature=0.2)
            rewritten = response.content.strip() if response.content else ""
        except Exception as exc:
            logger.warning("clarification_rewrite_failed", extra={"error": str(exc)})
            return None
        missing_options = missing_preserved_options(template_text, rewritten)
        if missing_options:
            logger.warning(
                "clarification_rewrite_validation_failed",
                extra={"missing_options": missing_options},
            )
            return None
        return rewritten or None


def _candidate_list(intent_result: IntentResult) -> list[str]:
    candidates = list(dict.fromkeys(intent_result.candidates))
    if candidates:
        return candidates
    return [intent_result.intent]


def option_lines(template_text: str) -> list[str]:
    """Extract option lines whose choices must survive LLM rewriting."""
    options: list[str] = []
    for line in template_text.splitlines():
        match = _OPTION_LINE_PATTERN.match(line)
        if match:
            options.append(match.group(1).strip())
    return options


def missing_preserved_options(template_text: str, rewritten_text: str) -> list[str]:
    """Return template options not represented in rewritten text."""
    normalized_rewrite = _normalize_option_text(rewritten_text)
    missing: list[str] = []
    for option in option_lines(template_text):
        if _normalize_option_text(option) not in normalized_rewrite:
            missing.append(option)
    return missing


def _normalize_option_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
