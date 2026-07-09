"""Deterministic-first facts extraction, run before intent classification.

Ownership and contract: Module 00 section 6. Deterministic extraction always
runs first for email, phone, quantity, budget, and company. The LLM is used
only as a structured-output extractor for the remaining fields when
deterministic extraction found nothing for them, and it never makes
control-flow decisions.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from app.llm.context import build_llm_messages
from app.llm.schemas import LLMClientProtocol
from app.logging_config import get_logger
from app.session.schemas import ConversationStateSchema, FactsSchema, FactsUpdate
from app.shared.intent_context import PromptProvider
from app.turns.schemas import ConversationTurnRead

logger = get_logger(__name__)

_EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_PATTERN = re.compile(r"(?:\+?\d{1,3}[\s-]?)?(?:\(?\d{2,4}\)?[\s-]?){2,4}\d{3,4}")
_QUANTITY_PATTERN = re.compile(r"\b(\d+)\s*(?:units?|pcs|pieces|qty|quantity)\b", re.IGNORECASE)
_BUDGET_PATTERN = re.compile(r"budget\s*(?:of|is|:)?\s*\$?\s*([\d,]+(?:\.\d+)?)\s*(k)?\b", re.IGNORECASE)
_COMPANY_PATTERN = re.compile(r"(?:company is|i work at|i'm from|we are|at)\s+([A-Z][\w&.,' -]{1,80}?)(?:\.|,|$)")

# Fields the LLM may fill when deterministic extraction found nothing for them.
FACT_LLM_FIELDS: tuple[str, ...] = (
    "company",
    "industry",
    "product_interest",
    "project_size",
    "location",
    "timeline",
)

_MIN_LLM_EXTRACTION_MESSAGE_LENGTH = 15


def _extract_deterministic(message: str) -> dict[str, Any]:
    extracted: dict[str, Any] = {}

    email_match = _EMAIL_PATTERN.search(message)
    if email_match:
        extracted["contact_email"] = email_match.group(0)

    phone_match = _PHONE_PATTERN.search(message)
    if phone_match and sum(char.isdigit() for char in phone_match.group(0)) >= 7:
        extracted["contact_phone"] = phone_match.group(0).strip()

    quantity_match = _QUANTITY_PATTERN.search(message)
    if quantity_match:
        extracted["quantity"] = int(quantity_match.group(1))

    budget_match = _BUDGET_PATTERN.search(message)
    if budget_match:
        raw_value = budget_match.group(1).replace(",", "")
        try:
            value = Decimal(raw_value)
            if budget_match.group(2):
                value *= 1000
            extracted["budget"] = value
        except InvalidOperation:
            pass

    company_match = _COMPANY_PATTERN.search(message)
    if company_match:
        extracted["company"] = company_match.group(1).strip()

    return extracted


def _normalize(field: str, value: Any) -> Any:
    """Validate/normalize one extracted value; return None to drop invalid fragments."""
    if value is None:
        return None
    if field == "quantity":
        return value if isinstance(value, int) and value > 0 else None
    if field == "budget":
        return value if isinstance(value, Decimal) and value >= 0 else None
    if field == "contact_email":
        return value if _EMAIL_PATTERN.fullmatch(value) else None
    if isinstance(value, str):
        stripped = value.strip()[:500]
        return stripped or None
    return value


def _values_equal(existing: Any, new: Any) -> bool:
    if isinstance(existing, str) and isinstance(new, str):
        return existing.strip().lower() == new.strip().lower()
    return existing == new


class FactsExtractor:
    """Sole facts-extraction entrypoint; runs after facts/state/recent turns are loaded."""

    async def extract(
        self,
        message: str,
        facts: FactsSchema,
        state: ConversationStateSchema,
        recent_turns: list[ConversationTurnRead],
        prompt_manager: PromptProvider,
        llm_client: LLMClientProtocol,
    ) -> FactsUpdate:
        """Return a validated FactsUpdate patch; empty/no-op fields are omitted."""
        patch: dict[str, Any] = {}

        for field, raw_value in _extract_deterministic(message).items():
            normalized = _normalize(field, raw_value)
            if normalized is None:
                continue
            existing = getattr(facts, field)
            if existing is not None and _values_equal(existing, normalized):
                continue
            # Deterministic matches come directly from the latest message, so a
            # conflicting value here is explicit and replaces the old one.
            patch[field] = normalized
            if existing is not None:
                logger.info(
                    "facts_field_updated",
                    extra={"field": field, "session_id": facts.session_id},
                )

        has_missing_field = any(
            field not in patch and getattr(facts, field) is None for field in FACT_LLM_FIELDS
        )
        if has_missing_field and len(message.strip()) > _MIN_LLM_EXTRACTION_MESSAGE_LENGTH:
            # Ask about every LLM-eligible field, not just the missing ones, so a
            # value conflicting with something already known is preserved (not
            # silently overwritten) rather than skipped before we even see it.
            llm_patch = await self._extract_via_llm(
                message, facts, state, recent_turns, prompt_manager, llm_client, list(FACT_LLM_FIELDS)
            )
            for field, raw_value in llm_patch.items():
                if field in patch:
                    continue
                normalized = _normalize(field, raw_value)
                if normalized is None:
                    continue
                existing = getattr(facts, field)
                if existing is not None:
                    if not _values_equal(existing, normalized):
                        # LLM-inferred values are not guaranteed explicit in the
                        # latest message, so an existing value wins on conflict.
                        logger.info(
                            "facts_conflict_preserved",
                            extra={"field": field, "session_id": facts.session_id},
                        )
                    continue
                patch[field] = normalized

        return FactsUpdate(**patch)

    async def _extract_via_llm(
        self,
        message: str,
        facts: FactsSchema,
        state: ConversationStateSchema,
        recent_turns: list[ConversationTurnRead],
        prompt_manager: PromptProvider,
        llm_client: LLMClientProtocol,
        missing_fields: list[str],
    ) -> dict[str, Any]:
        try:
            system_prompt = prompt_manager.get("classification", "extract_facts", "1")
            messages, _metadata = build_llm_messages(
                system_prompt=system_prompt,
                facts=facts,
                state=state,
                recent_turns=recent_turns,
                latest_user_message=message,
            )
            schema = {
                "type": "object",
                "properties": {field: {"type": ["string", "null"]} for field in missing_fields},
            }
            response = await llm_client.chat(messages, response_format=schema, temperature=0.0)
            if response.content is None:
                return {}
            parsed = json.loads(response.content)
            return {field: parsed.get(field) for field in missing_fields if parsed.get(field)}
        except Exception as exc:
            logger.warning("facts_llm_extraction_failed", extra={"error": str(exc)})
            return {}
