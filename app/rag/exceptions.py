"""Exceptions for the RAG engine."""

from __future__ import annotations


class RagError(Exception):
    """Base class for RAG engine failures."""


class RagQueryError(RagError):
    """Raised when a retrieval query cannot be built safely."""


class EmbeddingModelUnavailableError(RagError):
    """Raised when the configured embedding model cannot be loaded."""


class VectorStoreError(RagError):
    """Raised when Qdrant operations fail."""
