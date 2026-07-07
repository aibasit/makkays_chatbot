"""Tool Executor domain exceptions."""


class ToolExecutorError(Exception):
    """Base exception for tool execution failures."""


class PolicyViolationError(ToolExecutorError):
    """Raised when a plan step is present but denied by its Security Policy."""


class PlanViolationError(ToolExecutorError):
    """Raised when a tool call does not match the current deterministic plan."""


class RateLimitExceededError(ToolExecutorError):
    """Raised when a tool's rate-limit window has been exceeded."""


class PolicyFileMissingError(ToolExecutorError):
    """Raised at startup when a registered tool has no corresponding policy file."""
