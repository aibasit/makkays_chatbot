"""Ingest the pre-chunked JSONL RAG exports in `Updated Knowledge files/` into
dedicated Qdrant collections, one per product line (UPS, Battery, AVR).

Unlike `scripts/ingest_rag_knowledge.py` (which builds `ProductIngestRecord`s
backed by Postgres `products`/`product_specs` rows), this source is already a
flat, pre-chunked RAG export — one JSON object per line, each with `title`,
`text` (the text to embed), and a `metadata` dict carrying every structured
field (capacity_kva, phase, form_factor, ...) needed for exact-match filtering
alongside vector search. There is no Postgres table for this data; each chunk
lives entirely in Qdrant, with its full metadata stored as payload.

Each collection also gets a payload index on every filterable metadata field
present in that file, so a query can combine semantic search with an exact
filter (e.g. `capacity_kva == 6`) instead of relying on embeddings alone to
distinguish "6 kVA" from "8 kVA".

Point IDs are deterministic (`uuid5` of a fixed namespace + the chunk's own
`metadata.id`), so re-running this script is idempotent — it upserts in place
rather than creating duplicates.

Run (inside Docker, per this project's convention for anything needing
FlagEmbedding/qdrant-client):

    docker compose run --rm --no-deps backend python -m scripts.ingest_jsonl_knowledge
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from app.dependencies import get_settings
from app.rag.embeddings import BGE_M3_VECTOR_SIZE, BgeM3Embedder
from app.rag.qdrant_client import QdrantWrapper

_SOURCE_DIR = Path("Updated Knowledge files")
_NAMESPACE = uuid.UUID("6f6d5a2e-6b9d-4a3e-9b4b-1f0c9e7d5a10")
_BATCH_SIZE = 32

# One entry per source file: collection name, and which metadata fields get a
# payload index (and at what Qdrant schema type) for exact-match filtering.
_COLLECTIONS: dict[str, dict[str, Any]] = {
    "ipower_UPS_RAG.jsonl": {
        "collection": "ipower_ups_v1",
        "keyword_fields": [
            "doc_type", "category", "sub_category", "series", "type", "phase",
            "phase_in_out", "form_factor", "battery_configuration", "parallel_capable",
            "product_title",
        ],
        "float_fields": [
            "capacity_kva", "capacity_kw", "power_factor", "current_rating_a",
            "kva_min", "kva_max",
        ],
        "integer_fields": ["series_id", "model_count"],
    },
    "ipower_Battery_RAG.jsonl": {
        "collection": "ipower_battery_v1",
        "keyword_fields": [
            "doc_type", "category", "sub_category", "chemistry", "product_group",
            "service_life", "discharge_rate",
        ],
        "float_fields": [
            "nominal_voltage_vdc", "capacity_ah", "energy_kwh", "max_discharge_power_kw",
        ],
        "integer_fields": ["series_id", "max_units_parallel", "total_models", "total_series"],
    },
    "ipower_AVR_RAG.jsonl": {
        "collection": "ipower_avr_v1",
        "keyword_fields": [
            "doc_type", "category", "sub_category", "technology", "series",
            "product_group", "phase", "voltage_class",
        ],
        "float_fields": ["capacity_kva", "kva_min", "kva_max"],
        "integer_fields": ["series_id", "model_count", "total_models", "total_series"],
    },
}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open(encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path.name}:{line_number}: invalid JSON — {exc}") from exc
    return records


def _point_id(record: dict[str, Any]) -> str:
    """Derive a stable, idempotent point ID from the chunk's own identity.

    `metadata.id` alone isn't always unique: 15 UPS model codes are legitimately
    listed under two different series (the source data's own cross-series
    ambiguity, already surfaced once before in the UPS_Data CSVs' "Review Flag"
    column) — hashing the code alone would collide and silently drop one of
    the two real chunks on upsert. Including `series_id` keeps each distinct.
    """
    metadata = record.get("metadata", {})
    key = f"{metadata.get('doc_type', '')}:{metadata.get('id', '')}:{metadata.get('series_id', '')}"
    return str(uuid.uuid5(_NAMESPACE, key))


def _payload_for(record: dict[str, Any]) -> dict[str, Any]:
    metadata = record.get("metadata", {})
    return {**metadata, "title": record.get("title", ""), "text": record.get("text", "")}


def _ensure_payload_indexes(qdrant: QdrantWrapper, collection: str, spec: dict[str, Any]) -> None:
    from qdrant_client.http import models

    schema_by_field = {
        **{field: models.PayloadSchemaType.KEYWORD for field in spec["keyword_fields"]},
        **{field: models.PayloadSchemaType.FLOAT for field in spec["float_fields"]},
        **{field: models.PayloadSchemaType.INTEGER for field in spec["integer_fields"]},
    }
    for field_name, schema_type in schema_by_field.items():
        qdrant.client.create_payload_index(
            collection_name=collection,
            field_name=field_name,
            field_schema=schema_type,
        )


def _ingest_file(embedder: BgeM3Embedder, qdrant: QdrantWrapper, filename: str, spec: dict[str, Any]) -> int:
    path = _SOURCE_DIR / filename
    records = _read_jsonl(path)
    if not records:
        return 0

    collection = spec["collection"]
    qdrant.ensure_collection(collection, vector_size=BGE_M3_VECTOR_SIZE)
    _ensure_payload_indexes(qdrant, collection, spec)

    total = 0
    for start in range(0, len(records), _BATCH_SIZE):
        batch = records[start : start + _BATCH_SIZE]
        texts = [record["text"] for record in batch]
        vectors = embedder.embed(texts)
        points = [
            {
                "id": _point_id(record),
                "vector": vector,
                "payload": _payload_for(record),
            }
            for record, vector in zip(batch, vectors, strict=True)
        ]
        qdrant.upsert(collection, points)
        total += len(points)
        print(f"[{collection}] {total}/{len(records)} chunks upserted", flush=True)
    return total


def _run_test_query(embedder: BgeM3Embedder, qdrant: QdrantWrapper) -> None:
    """Prove vector search + exact metadata filtering work together, end to end."""
    collection = _COLLECTIONS["ipower_UPS_RAG.jsonl"]["collection"]
    query = "6 kVA single-phase online UPS"
    print(f"\nTest query on {collection!r}: {query!r} + filter capacity_kva == 6")
    vector = embedder.embed([query])[0]
    payload_filter = {"must": [{"key": "capacity_kva", "match": {"value": 6}}]}
    results = qdrant.search(collection, vector, payload_filter, limit=5)
    if not results:
        print("  No results — filter or index may not have applied correctly.")
        return
    for point in results:
        payload = point.payload
        print(
            f"  score={point.score:.4f}  model={payload.get('id')}  "
            f"title={payload.get('title')!r}  capacity_kva={payload.get('capacity_kva')}  "
            f"phase={payload.get('phase')}  form_factor={payload.get('form_factor')}"
        )


def main() -> None:
    settings = get_settings()
    embedder = BgeM3Embedder(settings.embedding.model_name)
    qdrant = QdrantWrapper(settings)

    grand_total = 0
    for filename, spec in _COLLECTIONS.items():
        print(f"\n=== {filename} -> {spec['collection']} ===", flush=True)
        count = _ingest_file(embedder, qdrant, filename, spec)
        grand_total += count
        print(f"[{spec['collection']}] done: {count} chunks", flush=True)

    print(f"\nTotal chunks ingested: {grand_total}")
    _run_test_query(embedder, qdrant)


if __name__ == "__main__":
    main()
