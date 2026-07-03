"""Exceptions raised by the LLM engine boundary."""


class LLMError(Exception):
    """Base class for LLM engine errors."""


class LLMTimeoutError(LLMError):
    """Raised when an Ollama request exceeds the configured timeout."""


class LLMMalformedOutputError(LLMError):
    """Raised when Ollama returns malformed or schema-invalid output."""


class LLMUnavailableError(LLMError):
    """Raised when Ollama is unreachable or returns an unavailable response."""
