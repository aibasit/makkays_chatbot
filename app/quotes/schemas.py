"""Quote domain schemas.

Module 12 owns the full Quote Builder and PDF export implementation. Only the
single canonical `quote_slots_complete` predicate is defined here for now, so
the Task Planner (Module 07) has one source of truth to import rather than
duplicating this check; Module 12 may refine the definition when it is built.
"""

from __future__ import annotations

from app.session.schemas import FactsSchema


def quote_slots_complete(facts: FactsSchema) -> bool:
    """Return whether enough facts exist to generate a quote."""
    return bool(facts.product_interest and facts.quantity and (facts.contact_email or facts.contact_phone))
