"""Quote domain schemas.

Module 12 owns the full Quote Builder and PDF export implementation. Only the
single canonical `quote_slots_complete` predicate is defined here for now, so
the Task Planner (Module 07) and Module 10's Security Policy predicate registry
share one source of truth rather than duplicating this check.
"""

from __future__ import annotations

from app.session.schemas import ConversationStateSchema, FactsSchema


def quote_slots_complete(facts: FactsSchema, state: ConversationStateSchema | None = None) -> bool:
    """Return whether enough facts exist to generate a quote.

    Accepts (and ignores) `state` so the signature matches the uniform
    `(facts, state) -> bool` shape Module 10's `PREDICATE_REGISTRY` requires.
    """
    return bool(
        facts.company is not None
        and facts.product_interest is not None
        and facts.quantity is not None
        and facts.budget is not None
    )
