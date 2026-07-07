"""Feature flag surface shared by the Task Planner and (eventually) Module 09."""

from __future__ import annotations

from pydantic import BaseModel


class FeatureFlags(BaseModel):
    """Per-tenant resolved feature flags read by Planner rule functions.

    Module 09 owns runtime resolution and persistence (tenant overrides layered
    on top of `app.config.FeatureFlagDefaults`); until it exists, this is the
    minimal read-only shape consumers such as the Task Planner need.
    """

    enable_rag: bool = True
    enable_quotes: bool = True
    enable_crm: bool = True
    enable_tickets: bool = True
    enable_image_upload: bool = False
    enable_llm_clarification_rewrite: bool = False
