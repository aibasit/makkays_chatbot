"""Exceptions for human handoff workflow."""

from __future__ import annotations


class HandoffError(Exception):
    """Base class for handoff failures."""


class InvalidHandoffTeamError(HandoffError):
    """Raised when a handoff target team is unsupported."""


class HandoffAlreadyInitiatedError(HandoffError):
    """Raised when a session already has an active handoff."""

    def __init__(self, reference_id: str) -> None:
        self.reference_id = reference_id
        super().__init__(f"Handoff already initiated with reference {reference_id}")
