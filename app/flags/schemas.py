"""FeatureFlags — the resolved snapshot consumed by Planner and Tool Executor."""

from __future__ import annotations

from pydantic import BaseModel


class FeatureFlags(BaseModel):
    """Per-turn snapshot of resolved feature flags (env defaults + DB overrides)."""

    # v4.1
    enable_rag: bool = True
    enable_quotes: bool = True
    enable_crm: bool = True
    enable_tickets: bool = True
    enable_image_upload: bool = False
    enable_llm_clarification_rewrite: bool = False
    # v4.2 — Product Intelligence
    enable_product_comparison: bool = True
    enable_compatibility_check: bool = True
    enable_accessory_recommendation: bool = True
    enable_pdf_search: bool = True
    # v4.2 — Solution & Wizard
    enable_solution_builder: bool = True
    enable_wizard: bool = True
    enable_use_case_recommendation: bool = True
    # v4.2 — Transactional & Ops
    enable_human_handoff: bool = True
    enable_availability_check: bool = False
    enable_multi_language: bool = False
    # v4.2 — Future Extension Stubs (always forced False by FeatureFlagsService)
    enable_voice_chat: bool = False
    enable_image_understanding: bool = False


# Derived from the model itself so the valid-name set can never drift out of
# sync with the fields actually defined above.
VALID_FLAG_NAMES: frozenset[str] = frozenset(FeatureFlags.model_fields.keys())

# Reserved stubs that must never be enabled, regardless of env or DB override.
FORCED_DISABLED_FLAGS: frozenset[str] = frozenset({"enable_voice_chat", "enable_image_understanding"})
