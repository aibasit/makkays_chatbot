"""LLM narration of a computed solution — never modifies prices or quantities."""

from __future__ import annotations

import json

from app.llm.schemas import ChatMessage, LLMClientProtocol
from app.logging_config import get_logger
from app.solution_builder.schemas import Solution

logger = get_logger(__name__)

_SYSTEM_PROMPT = (
    "You describe a pre-computed hardware solution (bill of materials) to a buyer "
    "in plain language. Summarize the line items and total in 2-4 sentences. Use "
    "only the numbers given — never recompute, round, or alter a price, quantity, "
    "or total."
)


class SolutionExplainer:
    """Narrates a Solution's line items/total. Never modifies the computed data."""

    async def explain(self, solution: Solution, llm_client: LLMClientProtocol) -> str:
        """Return a natural-language description of `solution`; never mutates it."""
        payload = json.dumps(
            {
                "use_case": solution.use_case,
                "line_items": [item.model_dump(mode="json") for item in solution.line_items],
                "total_estimate": str(solution.total_estimate),
                "currency": solution.currency,
            },
            separators=(",", ":"),
        )
        messages = [
            ChatMessage(role="system", content=_SYSTEM_PROMPT),
            ChatMessage(role="user", content=payload),
        ]
        try:
            response = await llm_client.chat(messages)
            return response.content or _fallback_summary(solution)
        except Exception as exc:
            logger.warning("solution_narration_failed", extra={"error": str(exc)})
            return _fallback_summary(solution)


def _fallback_summary(solution: Solution) -> str:
    items = ", ".join(f"{item.quantity}x {item.product_name}" for item in solution.line_items)
    return f"Solution: {items}. Total estimate: {solution.currency} {solution.total_estimate}."
