# Module 3 — Document Ingestion Pipeline

**Project:** Makkays AI Assistant (RAG Chatbot v4)
**Depends on:** Module 1 (Foundation), Module 2 (Database & Infrastructure)
**Blocks:** Module 4 (Embedding & Indexing)

---

## 1. Overview

This module turns raw source material — PDFs, DOCX brochures, and live Makkays
website pages — into clean, chunked, hashed, versioned text ready for embedding.
Nothing in this module touches Qdrant or embeddings; it stops at "document in →
tagged chunks out," persisted to Supabase's `documents`/`document_versions` tables.

---

## 2. Goals / Success Criteria

- A PDF or DOCX file, or a website URL, can be fed in and produces clean plain text
  with layout noise (headers/footers/nav menus/boilerplate) stripped.
- Text is split into semantically coherent chunks (not naive fixed-length splitting)
  sized appropriately for BGE-M3 + reranker input limits.
- Every chunk carries a `content_hash` so re-ingesting unchanged content is a no-op.
- Re-ingesting *changed* content creates a new `document_versions` row rather than
  silently overwriting history.
- Pipeline runs successfully end-to-end against 5–10 real Makkays pages/PDFs.

---

## 3. Folder/File Additions

```
backend/app/rag/
├── ingestion.py       # orchestrates parse → clean → chunk → hash → persist
├── crawler.py          # website crawling (requests + trafilatura)
├── chunking.py          # semantic-aware chunking + content hashing
└── parsers/
    ├── __init__.py
    ├── pdf_parser.py    # pymupdf
    └── docx_parser.py   # python-docx
```

---

## 4. Implementation Tasks

### 4.1 PDF parsing (`parsers/pdf_parser.py`)

- Use `pymupdf` (`fitz`) — extract text page by page, preserve page numbers as
  metadata (used later for citation-style grounding if needed).
- Strip repeated headers/footers: detect lines that appear identically on >50% of
  pages and drop them.
- Extract embedded tables where feasible (`page.find_tables()`); represent as
  markdown tables inline in the text stream so chunking treats them as normal text.

```python
def parse_pdf(file_path: str) -> list[dict]:
    """Returns [{"page": int, "text": str}, ...]"""
```

### 4.2 DOCX parsing (`parsers/docx_parser.py`)

- Use `python-docx` — walk paragraphs and tables in document order (not paragraphs
  then tables separately) to preserve reading order.
- Preserve heading levels (`Heading 1`/`Heading 2`) as markdown `#`/`##` prefixes —
  this feeds directly into semantic chunking boundaries in §4.4.

```python
def parse_docx(file_path: str) -> str:
    """Returns a single markdown-ish text blob with headings preserved."""
```

### 4.3 Website crawler (`crawler.py`)

- `requests` for fetching, `trafilatura` for main-content extraction (strips nav,
  footer, cookie banners, ads automatically).
- Respect `robots.txt`.
- Crawl scope: same-domain only, configurable max depth (default 3) and max pages
  (default 200) — this is a company site + brochures, not a general crawler.
- Store `source_url` and a fetch timestamp per page.

```python
def crawl_site(start_url: str, max_depth: int = 3, max_pages: int = 200) -> list[dict]:
    """Returns [{"url": str, "text": str, "title": str}, ...]"""
```

### 4.4 Text cleaning (shared, `ingestion.py`)

- Collapse repeated whitespace/newlines.
- Strip non-content artifacts trafilatura/pymupdf sometimes leave behind (page
  numbers like "3 / 12", "Copyright © Makkays" boilerplate lines).
- Normalize unicode (smart quotes → straight quotes, etc.) — matters for Roman Urdu
  and mixed-language content per the eval slice in Module 12.

### 4.5 Semantic chunking (`chunking.py`)

- Chunk on semantic boundaries, not fixed character counts: split at heading
  boundaries first, then within long sections split at paragraph boundaries, only
  falling back to sentence-level splitting if a paragraph alone exceeds the target
  size.
- Target chunk size: ~300–500 tokens, with ~50-token overlap between adjacent chunks
  from the same section (overlap preserves context that would otherwise be cut at a
  boundary).
- Attach metadata to every chunk: `document_id`, `chunk_index`, `category`,
  `source_type`, `source_url`, `language`.

```python
def chunk_text(text: str, target_tokens: int = 400, overlap_tokens: int = 50) -> list[dict]:
    """Returns [{"text": str, "chunk_index": int}, ...]"""
```

### 4.6 Content hashing (`chunking.py`)

- Hash at the **document** level (not per-chunk) using SHA-256 of the normalized full
  text, before chunking.
- On re-ingestion: compute new hash, compare to `documents.content_hash`.
  - Same hash → skip entirely (no new version, no re-embedding — this is what makes
    recrawl incremental and cheap).
  - Different hash → insert new `document_versions` row, update `documents.content_hash`
    and `updated_at`, and flag for re-embedding (Module 4 picks this up).

```python
import hashlib

def compute_content_hash(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()
```

### 4.7 Orchestration (`ingestion.py`)

```python
async def ingest_document(
    source_type: str,           # "pdf" | "docx" | "website"
    source_path_or_url: str,
    category: str,
    title: str,
    supabase: Client,
) -> dict:
    """
    1. Parse (4.1/4.2/4.3) → raw text
    2. Clean (4.4)
    3. Hash (4.6) → compare against existing documents row
    4. If unchanged: return {"status": "skipped", "document_id": ...}
    5. If new/changed: chunk (4.5), upsert documents + document_versions row,
       return chunks for Module 4 to embed + index
    """
```

- This function is the single entry point Module 4's embedding job calls, and Module
  9/10's document-upload admin route (Module 10) calls too — keep it source-agnostic.

---

## 5. Data Flow

```
PDF/DOCX file or URL
   │
   ▼
parsers/* or crawler.py  → raw text
   │
   ▼
clean_text()              → normalized text
   │
   ▼
compute_content_hash()     → compare vs documents.content_hash
   │                          ├── unchanged → skip
   │                          └── changed/new ↓
   ▼
chunk_text()                → list of tagged chunks
   │
   ▼
Supabase: documents + document_versions rows written
   │
   ▼
chunks handed to Module 4 (embedding + Qdrant indexing)
```

---

## 6. Testing & Validation Checklist

- [ ] A real Makkays PDF brochure parses with no garbled text, tables represented
      reasonably.
- [ ] A real Makkays DOCX parses with heading structure intact.
- [ ] Crawling a real Makkays page (or a public test site if not yet available)
      returns clean main content, no nav/footer boilerplate.
- [ ] Re-running ingestion on identical content produces `status: skipped`.
- [ ] Editing the source content and re-ingesting creates a new `document_versions`
      row and updates `content_hash`.
- [ ] Chunk sizes fall within the 300–500 token target on a representative sample.
- [ ] Chunks from a heading-structured document respect heading boundaries (spot
      check 5 chunks manually).

---

## 7. Deliverable

Working ingestion pipeline validated against 5–10 real Makkays pages/PDFs: document
in (file or URL) → clean, hashed, versioned, chunked text out, persisted to Supabase
and ready for Module 4.

---

## 8. Handoff Notes for Claude Code

- Keep chunk token counting consistent with whatever tokenizer Module 4's BGE-M3
  setup uses (or a close approximation) — mismatched token estimates here can cause
  Module 4 to silently truncate long chunks.
- `ingest_document()` must be idempotent and safe to call repeatedly — Module 9/10's
  manual re-upload flow and any future scheduled recrawl (`APScheduler`, Module 7)
  both call this same function.
- Do not embed or write to Qdrant from this module — that boundary belongs entirely
  to Module 4, keep this module's output a clean handoff of tagged chunk dicts.
