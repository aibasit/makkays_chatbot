"""Lazy Qdrant client wrapper for collection management, search, and upsert."""

from __future__ import annotations

import time
from typing import Any

from app.config import Settings
from app.logging_config import get_logger
from app.rag.embeddings import BGE_M3_VECTOR_SIZE
from app.rag.exceptions import VectorStoreError

logger = get_logger(__name__)


class QdrantWrapper:
    """Thin wrapper over qdrant-client with imports deferred until first use."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: Any | None = None

    @property
    def client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            from qdrant_client import QdrantClient
        except Exception as exc:
            raise VectorStoreError(
                "qdrant-client is required for Module 11. Install project dependencies "
                "inside Docker or add qdrant-client to the active environment."
            ) from exc
        api_key = self.settings.qdrant.api_key.get_secret_value()
        self._client = QdrantClient(url=self.settings.qdrant.url, api_key=api_key)
        return self._client

    def ensure_collection(
        self,
        name: str,
        *,
        vector_size: int = BGE_M3_VECTOR_SIZE,
        distance: str = "Cosine",
    ) -> None:
        """Create a collection if it is missing."""
        try:
            from qdrant_client.http import models

            existing = {collection.name for collection in self.client.get_collections().collections}
            if name in existing:
                return
            distance_value = getattr(models.Distance, distance.upper())
            self.client.create_collection(
                collection_name=name,
                vectors_config=models.VectorParams(size=vector_size, distance=distance_value),
            )
        except Exception as exc:
            raise VectorStoreError(f"Failed to ensure Qdrant collection {name!r}") from exc

    def search(
        self,
        collection: str,
        vector: list[float],
        payload_filter: dict[str, Any],
        limit: int,
    ) -> list[Any]:
        """Run a filtered vector search and return raw scored points."""
        started_at = time.perf_counter()
        try:
            query_filter = self._to_qdrant_filter(payload_filter)
            if hasattr(self.client, "search"):
                results = self.client.search(
                    collection_name=collection,
                    query_vector=vector,
                    query_filter=query_filter,
                    limit=limit,
                    with_payload=True,
                )
            else:
                response = self.client.query_points(
                    collection_name=collection,
                    query=vector,
                    query_filter=query_filter,
                    limit=limit,
                    with_payload=True,
                )
                results = list(getattr(response, "points", response))
        except Exception as exc:
            raise VectorStoreError(f"Qdrant search failed for {collection!r}") from exc
        logger.debug(
            "qdrant_search_complete",
            extra={
                "collection": collection,
                "result_count": len(results),
                "latency_ms": round((time.perf_counter() - started_at) * 1000, 2),
            },
        )
        return list(results)

    def upsert(self, collection: str, points: list[dict[str, Any]]) -> None:
        """Upsert points shaped as {'id', 'vector', 'payload'}."""
        try:
            from qdrant_client.http import models

            point_structs = [
                models.PointStruct(id=point["id"], vector=point["vector"], payload=point["payload"])
                for point in points
            ]
            self.client.upsert(collection_name=collection, points=point_structs)
        except Exception as exc:
            raise VectorStoreError(f"Qdrant upsert failed for {collection!r}") from exc

    @staticmethod
    def _to_qdrant_filter(payload_filter: dict[str, Any]) -> Any:
        from qdrant_client.http import models

        must_conditions = []
        for condition in payload_filter.get("must", []):
            key = condition.get("key")
            match = condition.get("match") or {}
            if not key:
                continue
            if "any" in match:
                must_conditions.append(
                    models.FieldCondition(key=key, match=models.MatchAny(any=match["any"]))
                )
            elif "value" in match:
                must_conditions.append(
                    models.FieldCondition(key=key, match=models.MatchValue(value=match["value"]))
                )
        return models.Filter(must=must_conditions)
