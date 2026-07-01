# Module 4 — Embedding & Indexing

**Project:** Makkays AI Assistant (RAG Chatbot v4)
**Depends on:** Module 2 (Database & Infrastructure — Qdrant collection exists),
Module 3 (Document Ingestion — produces tagged chunks)
**Blocks:** Module 5 (Retrieval Engine)

---

## 1. Overview

This module turns Module 3's tagged chunks into vectors and writes them into Qdrant.
It self-hosts **BGE-M3** to produce both a dense embedding and a sparse (lexical)
embedding per chunk in one pass, then upserts both into the `makkays_knowledge_base`
collection alongside full payload metadata. It also implements incremental updates so
re-ingesting unchanged content never triggers wasted re-embedding.

---

## 2. Goals / Success Criteria

- BGE-M3 runs locally (self-hosted via `FlagEmbedding`), producing a 1024-dim dense
  vector and a sparse vector (indices+values) per chunk.
- Every chunk from Module 3 is upserted into Qdrant with the full payload shape from
  the project's data model.
- Re-embedding is skipped for chunks belonging to unchanged documents (driven by
  Module 3's content-hash check).
- Real content from 5–10 Makkays pages/PDFs is queryable in Qdrant by the end of this
  module (even though querying itself is Module 5's job — this module proves the data
  is there and retrievable via a raw point-count/spot-check).

---

## 3. Folder/File Additions

```
backend/app/rag/
├── embeddings.py       # BGE-M3 wrapper — dense + sparse in one call
└── indexing.py          # chunk → embed → upsert into Qdrant, incremental logic
```

---

## 4. Implementation Tasks

### 4.1 BGE-M3 embedding wrapper (`embeddings.py`)

```python
from functools import lru_cache
from FlagEmbedding import BGEM3FlagModel

@lru_cache
def get_embedding_model() -> BGEM3FlagModel:
    # use_fp16=True halves memory with negligible quality loss — fine for this scale
    return BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)

def embed_chunks(texts: list[str]) -> list[dict]:
    """
    Returns [{"dense": [1024 floats], "sparse": {"indices": [...], "values": [...]}}, ...]
    """
    model = get_embedding_model()
    output = model.encode(
        texts,
        return_dense=True,
        return_sparse=True,
        return_colbert_vecs=False,   # not used — RRF fusion only needs dense+sparse
    )
    results = []
    for i in range(len(texts)):
        dense = output["dense_vecs"][i].tolist()
        sparse_weights = output["lexical_weights"][i]   # dict: {token_id: weight}
        results.append({
            "dense": dense,
            "sparse": {
                "indices": list(sparse_weights.keys()),
                "values": list(sparse_weights.values()),
            },
        })
    return results
```

- Load the model **once** at process startup (via `lru_cache`), not per-request — this
  is a multi-hundred-MB model, reloading it per call would be a severe perf bug.
- Batch embedding calls (e.g. 16–32 chunks per `encode()` call) rather than one chunk
  at a time — BGE-M3 benefits significantly from batching.

### 4.2 Qdrant indexing (`indexing.py`)

```python
from qdrant_client.models import PointStruct
import uuid

def build_points(chunks: list[dict], embeddings: list[dict], document_meta: dict) -> list[PointStruct]:
    points = []
    for chunk, emb in zip(chunks, embeddings):
        points.append(PointStruct(
            id=str(uuid.uuid4()),
            vector={
                "dense": emb["dense"],
                "sparse": emb["sparse"],
            },
            payload={
                "document_id": document_meta["document_id"],
                "title": document_meta["title"],
                "category": document_meta["category"],
                "source_type": document_meta["source_type"],
                "source_url": document_meta.get("source_url"),
                "version": document_meta["version"],
                "content_hash": document_meta["content_hash"],
                "language": document_meta.get("language", "en"),
                "is_active": True,
                "chunk_index": chunk["chunk_index"],
                "content": chunk["text"],
            },
        ))
    return points

async def index_chunks(qdrant_client, chunks: list[dict], document_meta: dict) -> int:
    embeddings = embed_chunks([c["text"] for c in chunks])
    points = build_points(chunks, embeddings, document_meta)
    qdrant_client.upsert(collection_name="makkays_knowledge_base", points=points)
    return len(points)
```

- Payload shape matches the Qdrant collection schema defined in the project's data
  model exactly — do not drop or rename fields, Module 5's filtering (by category,
  `is_active`, language) and Module 10's admin views both read this payload directly.

### 4.3 Incremental updates

- When Module 3 reports a document as `changed` (new version), **delete** the old
  version's points from Qdrant before inserting new ones, filtered by
  `document_id` + old `version`:

```python
from qdrant_client.models import Filter, FieldCondition, MatchValue

def delete_old_version(qdrant_client, document_id: str, old_version: int) -> None:
    qdrant_client.delete(
        collection_name="makkays_knowledge_base",
        points_selector=Filter(must=[
            FieldCondition(key="document_id", match=MatchValue(value=document_id)),
            FieldCondition(key="version", match=MatchValue(value=old_version)),
        ]),
    )
```

- When Module 3 reports `skipped` (unchanged), do nothing — no re-embed, no re-upsert.
  This is the entire point of content hashing: it makes recrawl cheap.
- When a document is deactivated (admin action, Module 10), set `is_active=false` via
  Qdrant's `set_payload` rather than deleting points outright — preserves history for
  potential reactivation without re-embedding.

### 4.4 Batch indexing entry point

```python
async def process_and_index(source_type, source_path_or_url, category, title, supabase, qdrant_client):
    result = await ingest_document(source_type, source_path_or_url, category, title, supabase)  # Module 3
    if result["status"] == "skipped":
        return result
    if result.get("previous_version"):
        delete_old_version(qdrant_client, result["document_id"], result["previous_version"])
    count = await index_chunks(qdrant_client, result["chunks"], result["document_meta"])
    return {"status": "indexed", "chunk_count": count, **result}
```

- This is the function the Day-5-style bulk ingestion script (and later Module 10's
  admin upload route) calls — a single call takes raw source all the way to
  queryable Qdrant points.

---

## 5. Testing & Validation Checklist

- [ ] `embed_chunks(["test sentence"])` returns a 1024-length dense vector and a
      non-empty sparse dict.
- [ ] Batching 20 chunks in one `embed_chunks()` call completes in reasonable time
      (benchmark once on target hardware — this determines Day-5 ingestion runtime).
- [ ] After indexing a test document, `qdrant_client.count("makkays_knowledge_base")`
      increases by exactly the chunk count.
- [ ] Payload on a spot-checked point contains all fields from §4.2 with correct
      values (title, category, content_hash, etc.).
- [ ] Re-running `process_and_index` on unchanged content returns `status: skipped`
      and point count is unchanged.
- [ ] Changing source content, re-running, results in old-version points deleted and
      new-version points present — verify via `document_id`+`version` filter query.
- [ ] Ingest and index all 5–10 real Makkays pages/PDFs; confirm total point count
      matches expected chunk count across all documents.

---

## 6. Deliverable

Real Makkays content (5–10 pages/PDFs) fully embedded and indexed in Qdrant with
correct dense+sparse vectors and complete payload metadata, with incremental
update/skip logic verified.

---

## 7. Handoff Notes for Claude Code

- Do not implement query-time retrieval here — this module is write-path only.
  Module 5 owns the `query_points` / RRF fusion call.
- Keep the BGE-M3 model instance and any Ollama/Groq client instances (Module 6)
  memory-isolated — if running on Render's free tier (limited RAM), loading BGE-M3
  + reranker (Module 5) simultaneously is the main memory pressure point; profile
  this before production rollout.
- If self-hosted BGE-M3 startup time becomes an issue on Render's free tier cold
  start, that's an operational concern (e.g. lazy-load on first request) —
  don't preemptively swap to a hosted embedding API here, the free self-hosted model
  is the correct choice per the project's stack decisions.
