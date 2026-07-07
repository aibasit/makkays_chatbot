"""Maps step names to tool implementations; builds the feature-flag-filtered LLM tool schema.

Tool implementations register themselves via `tool_registry.register(...)` in
their own module's `__init__.py` (imported by `app.main` at startup so tools
self-register) — this module never imports from Modules 11, 12, or 14 directly.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.flags.schemas import FeatureFlags
from app.tools.schemas import ExecutionContext, SessionContext, ToolExecutionResult

ToolFn = Callable[[SessionContext, ExecutionContext], Awaitable[ToolExecutionResult]]


class ToolRegistry:
    """Registry of step-name -> async tool implementation, filtered by feature flags."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolFn] = {}
        self._flag_gates: dict[str, str] = {}
        self._llm_schemas: dict[str, dict[str, Any]] = {}

    def register(
        self,
        name: str,
        fn: ToolFn,
        *,
        flag_name: str | None = None,
        llm_schema: dict[str, Any] | None = None,
    ) -> None:
        """Register one tool implementation; optionally gated by a feature flag."""
        self._tools[name] = fn
        if flag_name is not None:
            self._flag_gates[name] = flag_name
        if llm_schema is not None:
            self._llm_schemas[name] = llm_schema

    def get(self, name: str, flags: FeatureFlags) -> ToolFn | None:
        """Return the tool implementation if registered and not feature-flag-disabled."""
        if name not in self._tools:
            return None
        if not self._is_enabled(name, flags):
            return None
        return self._tools[name]

    def registered_tool_names(self) -> list[str]:
        """Return all registered tool names, regardless of flag state (for the policy self-check)."""
        return list(self._tools)

    def get_llm_tool_schema(self, flags: FeatureFlags) -> list[dict[str, Any]]:
        """Return LLM tool schemas for enabled tools only; disabled tools are never offered."""
        return [
            schema
            for name, schema in self._llm_schemas.items()
            if self._is_enabled(name, flags)
        ]

    def _is_enabled(self, name: str, flags: FeatureFlags) -> bool:
        flag_name = self._flag_gates.get(name)
        return flag_name is None or bool(getattr(flags, flag_name, True))


# Single module-level singleton — tool modules import `tool_registry` and call
# `.register(...)` on it at import time.
tool_registry = ToolRegistry()
