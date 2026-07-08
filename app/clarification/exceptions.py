"""Exceptions for the clarification flow."""

from __future__ import annotations


class ClarificationError(Exception):
    """Base class for clarification flow failures."""


class MaxClarificationRoundsExceededError(ClarificationError):
    """Raised when a session has already reached the clarification limit."""

    def __init__(self, session_id: str, rounds: int) -> None:
        self.session_id = session_id
        self.rounds = rounds
        super().__init__(
            f"Maximum clarification rounds exceeded for session {session_id!r}: {rounds}"
        )
