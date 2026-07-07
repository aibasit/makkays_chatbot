"""Router domain exceptions."""


class RouterError(Exception):
    """Base exception for router failures."""


class ClassificationFailedError(RouterError):
    """Raised internally when Tier 2 output cannot be trusted (never propagated to callers)."""
