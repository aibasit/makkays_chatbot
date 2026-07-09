"""Plain-language explanation of networking/power terminology."""

from __future__ import annotations

from app.llm.schemas import ChatMessage, LLMClientProtocol
from app.logging_config import get_logger

logger = get_logger(__name__)

_SYSTEM_PROMPT = (
    "You explain networking and power-hardware terminology (e.g. PoE, SFP, UPS, "
    "rack units) in plain, concise language for a non-technical buyer. Ground your "
    "answer in the provided context when given; otherwise rely on general industry "
    "knowledge. Keep the explanation to 2-4 sentences."
)


class SpecificationService:
    """Explains a spec term or piece of terminology in plain language."""

    async def explain(
        self,
        spec_term: str,
        context_text: str | None,
        llm_client: LLMClientProtocol,
    ) -> str:
        """Return a plain-language explanation of `spec_term`, grounded by `context_text` if given."""
        user_content = spec_term if not context_text else f"{spec_term}\n\nContext:\n{context_text}"
        messages = [
            ChatMessage(role="system", content=_SYSTEM_PROMPT),
            ChatMessage(role="user", content=user_content),
        ]
        try:
            response = await llm_client.chat(messages)
            return response.content or ""
        except Exception as exc:
            logger.warning("specification_explanation_failed", extra={"spec_term": spec_term, "error": str(exc)})
            return "I couldn't look up an explanation for that term just now — please try again."
