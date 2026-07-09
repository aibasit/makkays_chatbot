"""Response translation at the final assistant-message boundary."""

from __future__ import annotations

from app.language.schemas import LANGUAGE_NAMES, LanguageCode
from app.llm.schemas import ChatMessage, LLMClientProtocol
from app.logging_config import get_logger
from app.observability import registry as metrics
from app.prompts.manager import PromptProvider

logger = get_logger(__name__)


class TranslationService:
    """Translate final assistant messages while preserving formatting."""

    async def translate(
        self,
        text: str,
        target: LanguageCode,
        llm_client: LLMClientProtocol,
        prompt_provider: PromptProvider,
    ) -> str:
        """Translate text to target language, returning original text on failure."""
        if target == "en":
            return text

        try:
            template = prompt_provider.get("translation", "translate_response", "1")
            prompt = template.format(
                target_language_name=LANGUAGE_NAMES[target],
                text=text,
            )
            response = await llm_client.chat(
                [ChatMessage(role="user", content=prompt)],
                temperature=0.0,
            )
            translated = (response.content or "").strip()
            if not translated:
                raise ValueError("LLM returned empty translation")
        except Exception as exc:
            metrics.metrics_registry.increment_translation_request(target, False)
            logger.warning("translation_failed", extra={"target": target, "error": str(exc)})
            return text

        metrics.metrics_registry.increment_translation_request(target, True)
        logger.debug(
            "translation_succeeded",
            extra={"from": "en", "to": target, "character_count": len(text)},
        )
        return translated
