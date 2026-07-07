"""Security Policy Registry & Tool Executor (Module 10).

Importing this package imports `executor.py`, which registers the three
built-in tools (`respond`, `compare`, `request_missing_slots`) as a module-load
side effect — this mirrors how Modules 11/12/14 will register their own tools
in their `__init__.py` files.
"""

from __future__ import annotations

from typing import Any

from app.tools.exceptions import (
    PlanViolationError,
    PolicyFileMissingError,
    PolicyViolationError,
    RateLimitExceededError,
    ToolExecutorError,
)
from app.tools.executor import CRITICAL_STEPS, ToolExecutor
from app.tools.policy import PolicyRegistry, SecurityPolicy, policy_registry
from app.tools.registry import ToolRegistry, tool_registry
from app.tools.schemas import (
    ExecutionContext,
    PolicyCheckResult,
    SecurityPolicySchema,
    SessionContext,
    ToolExecutionResult,
)

__all__ = [
    "CRITICAL_STEPS",
    "ExecutionContext",
    "PlanViolationError",
    "PolicyCheckResult",
    "PolicyFileMissingError",
    "PolicyRegistry",
    "PolicyViolationError",
    "RateLimitExceededError",
    "SecurityPolicy",
    "SecurityPolicySchema",
    "SessionContext",
    "ToolExecutionResult",
    "ToolExecutor",
    "ToolExecutorError",
    "ToolRegistry",
    "policy_registry",
    "register_hooks",
    "tool_registry",
]


def register_hooks(app: Any, settings: Any) -> None:
    """Load Security Policies, then fail fast if any registered tool lacks one."""
    policy_registry.load()
    policy_registry.startup_self_check(tool_registry.registered_tool_names())
    app.state.tool_registry = tool_registry
    app.state.policy_registry = policy_registry
