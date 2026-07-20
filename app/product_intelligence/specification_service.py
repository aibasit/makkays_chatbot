"""Plain-language explanation of networking/power terminology."""

from __future__ import annotations

from app.llm.schemas import ChatMessage, LLMClientProtocol
from app.logging_config import get_logger

logger = get_logger(__name__)

_SYSTEM_PROMPT = (
    "You explain networking and power-hardware terminology (e.g. PoE, SFP, UPS, "
    "rack units) and product specifications for a non-technical buyer. If context is "
    "provided, it is real catalog data — ground your answer in it and never state a "
    "spec that contradicts it. If no context is provided: for a generic term (e.g. "
    "\"what is PoE\"), rely on general industry knowledge. But if the question names a "
    "specific model or product code and you were given no matching context, say "
    "plainly that you don't have that model's specifications rather than guessing or "
    "filling in plausible-sounding numbers — a specific model's specs are never "
    "general industry knowledge.\n\n"
    "Formatting: if the question asks for a specific product/model's specifications "
    "(not just what a term means), format the answer as a short Markdown heading with "
    "the product name followed by one bullet per spec field ('- **Field**: value'), "
    "listing every relevant field from the context — never compress a model's specs "
    "into a narrative paragraph, and never merge multiple distinct spec fields into "
    "one bullet. For a purely generic term explanation with no specific product "
    "involved, plain prose in 2-4 sentences is fine."
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
