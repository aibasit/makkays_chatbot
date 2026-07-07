"""Prompt Manager domain exceptions."""


class PromptNotFoundError(Exception):
    """Raised when a referenced prompt file is missing or its version is invalid."""
