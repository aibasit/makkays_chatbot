"""Session state domain exceptions."""


class SessionStateError(Exception):
    """Base exception for session state failures."""


class SessionNotFoundError(SessionStateError):
    """Raised when a session lookup must exist but is missing."""


class FactsCheckpointError(SessionStateError):
    """Raised when durable facts cannot be checkpointed to Postgres."""


class StateCheckpointError(SessionStateError):
    """Raised when conversation state cannot be checkpointed to Postgres."""
