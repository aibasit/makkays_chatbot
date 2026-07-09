"""Compatibility checks: explicit rules take precedence over LLM inference."""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.schemas import ChatMessage, LLMClientProtocol
from app.logging_config import get_logger
from app.product_intelligence.repository import CompatibilityRepository, ProductSpecRepository
from app.product_intelligence.schemas import CompatibilityResult

logger = get_logger(__name__)

_INFERENCE_SYSTEM_PROMPT = (
    "You assess networking/power hardware compatibility given each product's spec "
    "values. Respond with strict JSON: "
    '{"is_compatible": true|false, "notes": "one short sentence"}. '
    "If the specs are insufficient to tell, respond with is_compatible: false and say so in notes."
)

_INFERENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "is_compatible": {"type": "boolean"},
        "notes": {"type": "string"},
    },
    "required": ["is_compatible", "notes"],
}


class CompatibilityService:
    """Checks explicit compatibility rules first, falling back to LLM inference."""

    def __init__(
        self,
        db_session: AsyncSession,
        *,
        compatibility_repository: CompatibilityRepository | None = None,
        spec_repository: ProductSpecRepository | None = None,
    ) -> None:
        self.compatibility_repository = compatibility_repository or CompatibilityRepository(db_session)
        self.spec_repository = spec_repository or ProductSpecRepository(db_session)

    async def check(
        self,
        primary_product_id: UUID,
        secondary_product_id: UUID,
        compatibility_type: str,
        tenant_id: UUID,
        llm_client: LLMClientProtocol,
    ) -> CompatibilityResult:
        """Return the explicit rule if one exists, else an LLM-inferred estimate."""
        rule = await self.compatibility_repository.find(
            primary_product_id, secondary_product_id, compatibility_type, tenant_id
        )
        if rule is not None:
            logger.info(
                "compatibility_checked",
                extra={"source": "rule", "is_compatible": rule.is_compatible},
            )
            return CompatibilityResult(
                primary_product_id=primary_product_id,
                secondary_product_id=secondary_product_id,
                compatibility_type=compatibility_type,
                is_compatible=rule.is_compatible,
                source="rule",
                notes=rule.notes,
            )

        result = await self._infer(
            primary_product_id, secondary_product_id, compatibility_type, tenant_id, llm_client
        )
        logger.info(
            "compatibility_checked",
            extra={"source": "llm_inference", "is_compatible": result.is_compatible},
        )
        return result

    async def _infer(
        self,
        primary_product_id: UUID,
        secondary_product_id: UUID,
        compatibility_type: str,
        tenant_id: UUID,
        llm_client: LLMClientProtocol,
    ) -> CompatibilityResult:
        specs_by_product = await self.spec_repository.get_specs_for_products(
            [primary_product_id, secondary_product_id], tenant_id
        )
        specs_text = json.dumps(
            {
                "primary": {
                    spec.spec_key: spec.spec_value
                    for spec in specs_by_product.get(primary_product_id, [])
                },
                "secondary": {
                    spec.spec_key: spec.spec_value
                    for spec in specs_by_product.get(secondary_product_id, [])
                },
                "compatibility_type": compatibility_type,
            },
            separators=(",", ":"),
        )
        messages = [
            ChatMessage(role="system", content=_INFERENCE_SYSTEM_PROMPT),
            ChatMessage(role="user", content=specs_text),
        ]
        try:
            response = await llm_client.chat(messages, response_format=_INFERENCE_SCHEMA)
            parsed = json.loads(response.content or "{}")
            return CompatibilityResult(
                primary_product_id=primary_product_id,
                secondary_product_id=secondary_product_id,
                compatibility_type=compatibility_type,
                is_compatible=bool(parsed["is_compatible"]),
                source="llm_inference",
                notes=str(parsed.get("notes") or ""),
            )
        except Exception as exc:
            logger.warning("compatibility_inference_failed", extra={"error": str(exc)})
            return CompatibilityResult(
                primary_product_id=primary_product_id,
                secondary_product_id=secondary_product_id,
                compatibility_type=compatibility_type,
                is_compatible=None,
                source="llm_inference",
                notes="Unable to determine compatibility from available data",
            )
