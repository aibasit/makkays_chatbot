"""Embedding wrapper for BGE-M3, loaded lazily so normal boot stays light."""

from __future__ import annotations

import os
from typing import Any

from app.rag.exceptions import EmbeddingModelUnavailableError

BGE_M3_VECTOR_SIZE = 1024


class BgeM3Embedder:
    """Thin wrapper around FlagEmbedding's BGE-M3 dense encoder."""

    def __init__(self, model_name: str = "BAAI/bge-m3", model: Any | None = None) -> None:
        self.model_name = model_name
        self._model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one 1024-dimensional dense vector per text."""
        if not texts:
            return []
        model = self._get_model()
        encoded = model.encode(texts)
        vectors = self._extract_dense_vectors(encoded)
        for vector in vectors:
            if len(vector) != BGE_M3_VECTOR_SIZE:
                raise EmbeddingModelUnavailableError(
                    f"Expected {BGE_M3_VECTOR_SIZE}-dimensional embeddings, got {len(vector)}"
                )
        return vectors

    def _get_model(self) -> Any:
        if self._model is not None:
            return self._model
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        try:
            from FlagEmbedding import FlagModel
        except Exception as exc:
            raise EmbeddingModelUnavailableError(
                "FlagEmbedding is required for BGE-M3 embeddings. Install project dependencies "
                "inside Docker or add FlagEmbedding to the active environment."
            ) from exc
        self._model = FlagModel(self.model_name, use_fp16=True)
        return self._model

    @staticmethod
    def _extract_dense_vectors(encoded: Any) -> list[list[float]]:
        """Normalize the shapes returned by FlagEmbedding/fakes into plain lists."""
        dense = encoded.get("dense_vecs") if isinstance(encoded, dict) else encoded
        if hasattr(dense, "tolist"):
            dense = dense.tolist()
        if dense and hasattr(dense[0], "tolist"):
            dense = [item.tolist() for item in dense]
        return [[float(value) for value in vector] for vector in dense]
