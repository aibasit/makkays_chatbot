"""Task Planner domain exceptions."""


class PlannerError(Exception):
    """Base exception for planner failures."""


class UnknownIntentError(PlannerError):
    """Raised when build_plan is called with an intent that has no registered rule function."""
