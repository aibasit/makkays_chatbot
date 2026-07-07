"""Top-level per-turn control flow (Module 06).

`Orchestrator.on_turn` is the sole entrypoint Module 15's `/chat` endpoint will
call. Per Module 00 sections 5, 12, and 13, its full implementation calls
directly into `FeatureFlagsService.resolve` (Module 09), `ClarificationFlow.run`
(Module 13), `ToolExecutor.execute_plan` (Module 10), and `MetricsRegistry`
(Module 16) — none of which exist yet. Router (this package) and TaskPlanner
(Module 07) are both implemented and ready to be wired in once those remaining
modules land, in build order.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.llm.schemas import LLMClientProtocol
from app.shared.intent_context import PromptProvider


class Orchestrator:
    """Top-level per-turn control flow; not yet wired to its downstream modules."""

    async def on_turn(
        self,
        tenant_id: UUID,
        session_id: str,
        message: str,
        llm_client: LLMClientProtocol,
        prompt_provider: PromptProvider,
    ) -> Any:
        """Raise until Modules 08-10, 13, and 16 exist to complete the turn pipeline."""
        raise NotImplementedError(
            "Orchestrator.on_turn requires Modules 08 (Prompt Manager), "
            "09 (Feature Flags), 10 (Tool Executor), 13 (Clarification), and "
            "16 (Metrics), none of which are implemented yet."
        )
