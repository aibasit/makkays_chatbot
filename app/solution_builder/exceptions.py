"""Solution Builder domain exceptions."""


class SolutionBuilderError(Exception):
    """Base exception for solution builder failures."""


class WizardAlreadyCompleteError(SolutionBuilderError):
    """Raised when advance() is called on a wizard session that already completed."""


class UseCaseNotFoundError(SolutionBuilderError):
    """Raised when neither a use-case profile nor any product matches the use case."""


class InsufficientProductDataError(SolutionBuilderError):
    """Raised when the tenant's catalog has no products for a required BOM category."""
