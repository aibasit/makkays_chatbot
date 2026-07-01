# Module 2 — Database & Infrastructure

**Project:** Makkays AI Assistant (RAG Chatbot v4)
**Depends on:** Module 1 (Project Foundation)
**Blocks:** Module 3 (Ingestion), Module 4 (Embedding/Indexing), Module 5 (Retrieval),
Module 7 (Chat API), Module 9 (Leads), Module 10 (Admin)

---

## 1. Overview

This module stands up the three managed free-tier services that make v4 different from
v3: **Supabase** (Postgres + Auth + Storage), **Qdrant Cloud** (native hybrid vector
search), and **Upstash Redis** (real distributed cache). By the end of this module,
every one of these is reachable from the FastAPI backend via a typed client injected
through `dependencies.py`, and the full relational schema exists in Supabase.

---

## 2. Goals / Success Criteria

- Supabase project created; full schema from §5 applied via migration, not the SQL
  editor ad-hoc (so it's reproducible).
- Qdrant Cloud cluster created; `makkays_knowledge_base` collection exists with both
  `dense` (1024-dim, BGE-M3) and `sparse` vector fields configured.
- Upstash Redis database created; set/get round trip verified from FastAPI.
- All three clients are singletons provided via `Depends()`, matching the DI pattern
  from Module 1.
- Admin auth (Supabase Auth) has at least one seeded admin user for Module 10 to use
  later.

---

## 3. Environment Variables (now populated for real)

```env
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<service-role-key>   # backend only, never exposed to widget
SUPABASE_ANON_KEY=<anon-key>                   # if any client-side Supabase calls are ever needed

QDRANT_URL=https://<cluster-id>.<region>.cloud.qdrant.io
QDRANT_API_KEY=<qdrant-api-key>

UPSTASH_REDIS_REST_URL=https://<db-name>.upstash.io
UPSTASH_REDIS_REST_TOKEN=<upstash-token>
```

Free-tier limits to keep in mind (from the project's tier constraints):
- Supabase: 500MB DB, 1GB storage, 50k MAU auth.
- Qdrant: 1GB cluster, forever free.
- Upstash: 10,000 commands/day, 256MB.

---

## 4. Folder/File Additions

```
backend/app/
├── db/
│   ├── __init__.py
│   ├── supabase_client.py       # singleton Supabase client
│   └── models.py                 # pydantic models mirroring the schema (read/write DTOs)
├── cache/
│   ├── __init__.py
│   └── redis_client.py           # singleton Upstash Redis client (REST-based)
├── rag/
│   ├── __init__.py
│   └── qdrant_client.py          # singleton Qdrant client + collection bootstrap
└── migrations/
    └── 0001_init_schema.sql      # raw SQL migration for Supabase
```

---

## 5. Database Schema (Supabase / Postgres)

Written as a single migration file, `migrations/0001_init_schema.sql`. Run via
Supabase CLI (`supabase db push`) or the SQL editor — either way, keep this file as
the source of truth, don't hand-edit the live schema afterward without updating it.

```sql
-- Extensions
create extension if not exists "uuid-ossp";
create extension if not exists pgcrypto;

-- Admin users (Supabase Auth handles credentials; this table holds app-level profile)
create table admin_users (
    id uuid primary key references auth.users(id) on delete cascade,
    full_name text,
    role text not null default 'admin',       -- admin | superadmin
    created_at timestamptz not null default now()
);

-- Documents (source of truth for ingested content, one row per source file/page)
create table documents (
    id uuid primary key default uuid_generate_v4(),
    title text not null,
    category text not null,                    -- Power Solutions | Business Automation | ...
    source_type text not null check (source_type in ('website','pdf','docx')),
    source_url text,
    storage_path text,                          -- Supabase Storage path for original file
    language text default 'en',
    is_active boolean not null default true,
    content_hash text not null,                 -- for incremental recrawl (Module 3)
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

-- Document versions (append-only history; content_hash changes create a new version)
create table document_versions (
    id uuid primary key default uuid_generate_v4(),
    document_id uuid not null references documents(id) on delete cascade,
    version int not null,
    content_hash text not null,
    storage_path text,
    created_at timestamptz not null default now(),
    unique (document_id, version)
);

-- Chat sessions
create table chat_sessions (
    id uuid primary key default uuid_generate_v4(),
    visitor_id text,                            -- anonymous widget-side id (cookie/localStorage)
    language text default 'en',
    started_at timestamptz not null default now(),
    ended_at timestamptz
);

-- Chat messages
create table chat_messages (
    id uuid primary key default uuid_generate_v4(),
    session_id uuid not null references chat_sessions(id) on delete cascade,
    role text not null check (role in ('user','assistant','system')),
    content text not null,
    confidence_score numeric(4,3),              -- from Module 5 confidence policy
    retrieved_chunk_ids text[],                  -- Qdrant point ids used for this answer
    created_at timestamptz not null default now()
);

-- Leads (buying-intent captures)
create table leads (
    id uuid primary key default uuid_generate_v4(),
    session_id uuid references chat_sessions(id) on delete set null,
    name text,
    email text,
    phone text,
    category text check (category in
        ('Power','Business Automation','Test & Measurement','Services & Support','General Inquiry')),
    message text,
    status text not null default 'new',          -- new | contacted | closed
    created_at timestamptz not null default now()
);

-- Support tickets (fallback → email handoff, Module 9/12)
create table support_tickets (
    id uuid primary key default uuid_generate_v4(),
    session_id uuid references chat_sessions(id) on delete set null,
    subject text not null,
    description text not null,
    contact_email text,
    status text not null default 'open',          -- open | in_progress | resolved
    created_at timestamptz not null default now()
);

-- Unanswered questions (low-confidence queries logged for review/eval)
create table unanswered_questions (
    id uuid primary key default uuid_generate_v4(),
    session_id uuid references chat_sessions(id) on delete set null,
    question text not null,
    confidence_score numeric(4,3),
    created_at timestamptz not null default now()
);

-- Feedback (thumbs up/down on answers)
create table feedback (
    id uuid primary key default uuid_generate_v4(),
    message_id uuid references chat_messages(id) on delete cascade,
    rating text not null check (rating in ('up','down')),
    comment text,
    created_at timestamptz not null default now()
);

-- Audit logs (admin actions — document edits, deletes, logins)
create table audit_logs (
    id uuid primary key default uuid_generate_v4(),
    admin_id uuid references admin_users(id) on delete set null,
    action text not null,
    entity_type text,
    entity_id text,
    metadata jsonb,
    created_at timestamptz not null default now()
);

-- Indexes
create index idx_documents_active on documents(is_active);
create index idx_chat_messages_session on chat_messages(session_id);
create index idx_leads_status on leads(status);
create index idx_tickets_status on support_tickets(status);
create index idx_unanswered_created on unanswered_questions(created_at desc);

-- Row Level Security: lock everything down, backend uses service role key which bypasses RLS
alter table admin_users enable row level security;
alter table documents enable row level security;
alter table document_versions enable row level security;
alter table chat_sessions enable row level security;
alter table chat_messages enable row level security;
alter table leads enable row level security;
alter table support_tickets enable row level security;
alter table unanswered_questions enable row level security;
alter table feedback enable row level security;
alter table audit_logs enable row level security;
-- No public policies added — all access goes through the backend's service-role client.
```

---

## 6. Implementation Tasks

### 6.1 Supabase client (`db/supabase_client.py`)

```python
from functools import lru_cache
from supabase import create_client, Client
from app.config import get_settings

@lru_cache
def get_supabase() -> Client:
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_service_role_key)
```

- Backend always uses the **service role key** (bypasses RLS) — the widget/frontend
  never talks to Supabase directly, everything routes through FastAPI.

### 6.2 Qdrant client + collection bootstrap (`rag/qdrant_client.py`)

```python
from functools import lru_cache
from qdrant_client import QdrantClient
from qdrant_client.models import (
    VectorParams, Distance, SparseVectorParams, SparseIndexParams
)
from app.config import get_settings

COLLECTION_NAME = "makkays_knowledge_base"

@lru_cache
def get_qdrant() -> QdrantClient:
    settings = get_settings()
    return QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)

def ensure_collection(client: QdrantClient) -> None:
    if client.collection_exists(COLLECTION_NAME):
        return
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config={"dense": VectorParams(size=1024, distance=Distance.COSINE)},
        sparse_vectors_config={"sparse": SparseVectorParams(index=SparseIndexParams())},
    )
```

- `ensure_collection()` is called once at startup (`main.py` lifespan event) — safe to
  call repeatedly, it's idempotent.
- Vector size **1024** matches BGE-M3's dense output — do not change without also
  changing Module 4's embedding config.

### 6.3 Upstash Redis client (`cache/redis_client.py`)

```python
from functools import lru_cache
from upstash_redis import Redis
from app.config import get_settings

@lru_cache
def get_redis() -> Redis:
    settings = get_settings()
    return Redis(url=settings.upstash_redis_rest_url, token=settings.upstash_redis_rest_token)
```

- Upstash's REST client is used (not raw TCP `redis-py`) — this is what makes it work
  from serverless/Render's free tier without persistent connections.

### 6.4 Wire into `dependencies.py`

```python
from app.db.supabase_client import get_supabase
from app.rag.qdrant_client import get_qdrant
from app.cache.redis_client import get_redis

SupabaseDep = Annotated[Client, Depends(get_supabase)]
QdrantDep = Annotated[QdrantClient, Depends(get_qdrant)]
RedisDep = Annotated[Redis, Depends(get_redis)]
```

### 6.5 Seed one admin user

- Via Supabase dashboard (Auth → Users → Invite) or CLI, create the first admin
  account, then insert a matching row into `admin_users` with `role='superadmin'`.
- Module 10 (Admin Dashboard) authenticates against this.

---

## 7. Testing & Validation Checklist

- [ ] `migrations/0001_init_schema.sql` applies cleanly to a fresh Supabase project.
- [ ] Every table from §5 exists; RLS is enabled on all of them.
- [ ] `get_supabase().table("documents").select("*").execute()` returns `[]` (empty,
      no error) on a fresh DB.
- [ ] `ensure_collection()` creates `makkays_knowledge_base` with both `dense` and
      `sparse` vector configs — confirm via Qdrant dashboard.
- [ ] `get_redis().set("smoke_test", "ok")` then `.get("smoke_test")` round-trips
      correctly.
- [ ] One admin user exists in both `auth.users` and `admin_users`.
- [ ] All three connection strings load from `.env` with no hardcoded secrets in code.

---

## 8. Deliverable

Backend that, on boot, connects successfully to Supabase, Qdrant, and Upstash Redis;
full relational schema live; empty-but-correctly-shaped Qdrant collection ready for
Module 4 to populate.

---

## 9. Handoff Notes for Claude Code

- Do **not** add business logic (chat, leads, documents) into this module's clients —
  they stay thin (connection + collection bootstrap only). Business logic lives in
  `services/` starting Module 7 onward.
-- If Qdrant free-tier 1GB or Upstash's 10k/day commands ever become a real constraint,
  that's an operational concern, not something to work around here with a
  DIY substitute — the whole point of v4 is these tiers are sufficient at this scale.
- Keep `document_versions` append-only — Module 3's incremental recrawl logic (content
  hashing) depends on being able to diff against the latest version, never mutate old
  version rows.
