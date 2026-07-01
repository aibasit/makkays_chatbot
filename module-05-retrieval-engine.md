# Module 5 — Retrieval Engine (RAG Core)

**Project:** Makkays AI Assistant (RAG Chatbot v4)
**Depends on:** Module 4 (Embedding & Indexing — Qdrant populated with real content)
**Blocks:** Module 6 (LLM Integration), Module 7 (Chat API)

---

## 1. Overview

This is the heart of the RAG system: turning a user query into a ranked, confident,
grounded set of chunks. It covers query preprocessing, native Qdrant hybrid search
(dense + sparse fused via RRF), reranking with `bge-reranker-large`, confidence
scoring, and groundedness checking. By the end of this module, a raw query string
produces a reranked top-5 chunk list with a confidence band — everything Module 6
needs to generate an answer.

---

## 2. Goals / Success Criteria

- Query → Qdrant native hybrid search (RRF fusion, top 20) → `bge-reranker-large` →
  top 5 → confidence score, working end-to-end against real indexed content.
- Confidence bands (§6) correctly gate downstream behavior (normal answer / hedged
  answer / fallback).
- Groundedness check module exists (verification logic) — full integration with
  generation happens in Module 6, but the standalone checking function is built here.
- Manual testing against real questions about Makkays content returns sensible,
  correctly-ranked chunks.

---

## 3. Folder/File Additions

```
backend/app/rag/
├── query_preprocessing.py   # language detect + query rewrite
├── hybrid_search.py          # native Qdrant RRF fusion query
├── reranker.py                # bge-reranker-large, self-hosted
├── confidence.py              # confidence scoring from rerank scores
└── groundedness.py            # claim-vs-chunk verification
```

---

## 4. Implementation Tasks

### 4.1 Query preprocessing (`query_preprocessing.py`)

- **Language detection**: use `langdetect` or `fasttext` lightweight language ID to
  tag the query as `en`, `ur`, or `roman-ur` (Roman Urdu needs a heuristic — e.g.
  Latin script + common Roman-Urdu tokens like "hai", "kya", "kaise" — since standard
  language detectors misclassify Roman Urdu as English).
- **Query rewrite**: for multi-turn chats (Module 6/7 conversation memory), rewrite
  follow-up queries that depend on prior context into standalone queries before
  retrieval (e.g. "what about the UPS one?" → "what is the price of the UPS power
  solution?" using recent chat history). This can be a lightweight Groq call itself —
  cheap, fast model, single-purpose prompt.

```python
def detect_language(query: str) -> str: ...
def rewrite_query(query: str, chat_history: list[dict]) -> str: ...
```

### 4.2 Hybrid search — native Qdrant RRF fusion (`hybrid_search.py`)

This is the module that makes v4's correction from v3 real — actual native Qdrant
fusion, not a DIY `pgvector`+`tsvector` approximation.

```python
from qdrant_client.models import Prefetch, FusionQuery, Fusion, Filter, FieldCondition, MatchValue
from app.rag.embeddings import embed_chunks

def hybrid_search(qdrant_client, query: str, limit: int = 20, category: str | None = None):
    query_emb = embed_chunks([query])[0]

    must_filters = [FieldCondition(key="is_active", match=MatchValue(value=True))]
    if category:
        must_filters.append(FieldCondition(key="category", match=MatchValue(value=category)))

    results = qdrant_client.query_points(
        collection_name="makkays_knowledge_base",
        prefetch=[
            Prefetch(query=query_emb["dense"], using="dense", limit=limit),
            Prefetch(query=query_emb["sparse"], using="sparse", limit=limit),
        ],
        query=FusionQuery(fusion=Fusion.RRF),
        query_filter=Filter(must=must_filters),
        limit=limit,
    )
    return results.points
```

- This preserves exact technical tokens (UPS, BESS, AVR, model numbers) via the
  sparse channel while dense catches semantically related queries — the whole reason
  hybrid search was chosen. Do not fall back to dense-only search for convenience.
- `is_active=True` filter ensures deactivated/superseded document versions never
  surface (ties back to Module 4's incremental update logic).

### 4.3 Reranking (`reranker.py`)

```python
from functools import lru_cache
from FlagEmbedding import FlagReranker

@lru_cache
def get_reranker() -> FlagReranker:
    return FlagReranker("BAAI/bge-reranker-large", use_fp16=True)

def rerank(query: str, candidates: list[dict], top_k: int = 5) -> list[dict]:
    """candidates: [{"id": ..., "content": ..., "payload": {...}}, ...] from hybrid_search"""
    reranker = get_reranker()
    pairs = [[query, c["content"]] for c in candidates]
    scores = reranker.compute_score(pairs, normalize=True)  # normalized to 0-1 range
    for c, s in zip(candidates, scores):
        c["rerank_score"] = s
    ranked = sorted(candidates, key=lambda c: c["rerank_score"], reverse=True)
    return ranked[:top_k]
```

- Full-size `bge-reranker-large` — no lighter substitute, per the project's stack
  decision (this was v3's compromise, restored in v4).
- Load once via `lru_cache`, same pattern as BGE-M3 in Module 4 — this is the other
  significant memory consumer alongside the embedding model, keep this in mind for
  production sizing.

### 4.4 Confidence scoring (`confidence.py`)

Implements the project's confidence policy exactly:

```python
def score_confidence(ranked_chunks: list[dict]) -> dict:
    if not ranked_chunks:
        return {"band": "fallback", "score": 0.0, "margin": 0.0}

    top_score = ranked_chunks[0]["rerank_score"]
    second_score = ranked_chunks[1]["rerank_score"] if len(ranked_chunks) > 1 else 0.0
    margin = top_score - second_score

    if top_score >= 0.80:
        band = "normal"
    elif 0.55 <= top_score < 0.80:
        band = "hedged"          # prefix "Based on available information..."
    else:
        band = "fallback"        # offer to collect contact details

    if margin < 0.02:             # near-zero margin treated as low-confidence signal
        band = "fallback"

    return {"band": band, "score": top_score, "margin": margin}
```

- `band` drives Module 6's prompt construction (hedged prefix) and Module 9's lead
  capture trigger (fallback band → offer contact form).

### 4.5 Groundedness check (`groundedness.py`)

- Standalone function; full integration into the generate→check→return loop happens
  in Module 6, but the checking logic itself belongs here since it's a retrieval-side
  concern (verifying generation against *retrieved* chunks).

```python
def check_groundedness(answer: str, source_chunks: list[dict]) -> dict:
    """
    Lightweight approach at this scale: extract candidate factual claims from the
    answer (numbers, named entities, specific product/spec mentions), verify each
    appears in (or is directly supported by) the concatenated source_chunks text.
    Returns {"grounded": bool, "unsupported_claims": [...]}
    A cheap Groq call with a strict verification prompt is acceptable here instead of
    building a custom NLI model — keep it fast (short prompt, short output).
    """
```

- This function returns a verdict; Module 6 is responsible for what happens on
  `grounded: False` (retry with more explicit "only use provided context" instruction,
  or fall back to "couldn't find confirmed information").

---

## 5. Data Flow

```
raw user query
   │
   ▼
query_preprocessing.py   → language tag, rewritten standalone query
   │
   ▼
hybrid_search.py           → Qdrant RRF fusion, top 20 (dense + sparse)
   │
   ▼
reranker.py                 → bge-reranker-large, top 5
   │
   ▼
confidence.py                → band: normal | hedged | fallback
   │
   ▼
[handed to Module 6 for generation]
   │
   ▼
groundedness.py (post-generation) → grounded: bool
```

---

## 6. Confidence Policy (reference)

```
score = top rerank score, margin = top score − second score

score ≥ 0.80              → answer normally
0.55 ≤ score < 0.80        → answer, prefixed "Based on available information..."
score < 0.55 OR margin ~0  → fallback + offer to collect contact details
```

---

## 7. Testing & Validation Checklist

- [ ] `hybrid_search()` returns results for both a keyword-heavy query ("AVR model
      number X") and a semantic query ("what solutions help with unstable grid
      power?") — confirm sparse channel catches the former, dense catches the latter.
- [ ] Reranking measurably reorders the top-20 candidates vs. raw fusion order on at
      least a few manually inspected queries.
- [ ] Confidence bands trigger correctly: craft one query that should score high
      (exact match to indexed content), one ambiguous, one clearly out-of-scope.
- [ ] `category` filter in `hybrid_search()` correctly restricts results when passed.
- [ ] `check_groundedness()` correctly flags an answer containing a fabricated number
      not present in source chunks.
- [ ] Roman Urdu query gets tagged correctly by `detect_language()` on a handful of
      sample phrases (full eval suite is Module 12, this is just a smoke test).
- [ ] End-to-end manual test: 10 real questions about indexed Makkays content, inspect
      retrieved chunks and confidence bands for each.

---

## 8. Deliverable

Query → ranked chunk list → confidence score, using real native hybrid search and
full-size reranking, validated manually against real indexed content and a range of
query types (keyword-heavy, semantic, ambiguous, out-of-scope).

---

## 9. Handoff Notes for Claude Code

- Keep `hybrid_search`, `rerank`, `score_confidence`, and `check_groundedness` as
  independently testable pure(ish) functions — Module 6 orchestrates them but should
  not need to know their internals, and Module 12's eval harness calls them directly
  for retrieval-only evaluation separate from full-pipeline evaluation.
- Do not hardcode the 0.80/0.55 thresholds in multiple places — keep them as named
  constants in `confidence.py` so Module 12's tuning pass (Day 14) has one place to
  adjust them based on eval results.
- `check_groundedness()`'s Groq call is a second LLM call per turn (on top of Module
  6's generation call) — be mindful of this doubling rate-limit pressure; Module 6
  should route both through the same Groq-with-Ollama-fallback provider abstraction.
