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
    # `import app.rag` would rebind the local name `app` to the top-level `app`
    # package (that's how `import x.y` binds `x`), clobbering the FastAPI `app`
    # parameter for the rest of this function — `from app import rag` avoids it.
    from app import rag  # noqa: F401
    from app.availability.tool import check_availability_tool
    from app.crm.service import create_lead_tool
    from app.handoff.handoff_service import initiate_handoff_tool
    from app.quotes.builder import generate_quote_tool

    tool_registry.register("create_lead", create_lead_tool, flag_name="enable_crm")
    tool_registry.register("generate_quote", generate_quote_tool, flag_name="enable_quotes")
    tool_registry.register("initiate_handoff", initiate_handoff_tool, flag_name="enable_human_handoff")
    tool_registry.register("check_availability", check_availability_tool, flag_name="enable_availability_check")

    policy_registry.load()
    policy_registry.startup_self_check(tool_registry.registered_tool_names())
    app.state.tool_registry = tool_registry
    app.state.policy_registry = policy_registry
