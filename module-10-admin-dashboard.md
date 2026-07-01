# Module 10 — Admin Dashboard

**Project:** Makkays AI Assistant (RAG Chatbot v4)
**Depends on:** Module 2 (Supabase Auth + schema), Module 3/4 (document ingestion +
indexing — dashboard triggers these), Module 9 (leads/tickets data to display)
**Blocks:** Admin surface for final release

---

## 1. Overview

A server-rendered admin panel (Jinja2 + HTMX, no separate hosted frontend service)
giving the Makkays team visibility into and control over documents, conversations,
leads, unanswered questions, and feedback — authenticated via Supabase Auth.

---

## 2. Goals / Success Criteria

- Admin login works against the seeded admin user (Module 2) via Supabase Auth.
- Document management: upload PDF/DOCX, trigger re-crawl of a URL, view/deactivate
  documents, see version history.
- Conversation viewer: browse chat sessions, read full transcripts.
- Leads management: view/filter leads by status/category, update status.
- Unanswered questions view: surfaces gaps for content/eval improvement.
- Feedback view: thumbs up/down aggregate + individual comments.
- No separate hosted frontend — served directly from FastAPI via Jinja2 templates,
  HTMX handles interactivity without a JS framework.

---

## 3. Folder/File Additions

```
backend/app/
├── templates/
│   ├── base.html                 # shared layout, nav, HTMX/Tailwind CDN includes
│   ├── login.html
│   ├── dashboard.html             # overview/stats landing page
│   ├── documents/
│   │   ├── list.html
│   │   ├── upload.html
│   │   └── detail.html             # version history for one document
│   ├── conversations/
│   │   ├── list.html
│   │   └── detail.html              # full transcript
│   ├── leads/
│   │   └── list.html
│   ├── tickets/
│   │   └── list.html
│   ├── unanswered/
│   │   └── list.html
│   └── feedback/
│       └── list.html
├── api/
│   └── admin.py                    # all admin routes, auth-protected
└── services/
    └── admin_auth_service.py        # Supabase Auth session verification
```

---

## 4. Implementation Tasks

### 4.1 Authentication (`admin_auth_service.py`)

```python
from fastapi import Request, HTTPException
from app.db.supabase_client import get_supabase

async def get_current_admin(request: Request):
    token = request.cookies.get("admin_session")
    if not token:
        raise HTTPException(status_code=303, headers={"Location": "/admin/login"})
    supabase = get_supabase()
    try:
        user = supabase.auth.get_user(token)
    except Exception:
        raise HTTPException(status_code=303, headers={"Location": "/admin/login"})
    admin_row = supabase.table("admin_users").select("*").eq("id", user.user.id).execute()
    if not admin_row.data:
        raise HTTPException(status_code=403, detail="Not an admin")
    return admin_row.data[0]
```

```python
@router.post("/admin/login")
async def login(email: str = Form(...), password: str = Form(...)):
    supabase = get_supabase()
    session = supabase.auth.sign_in_with_password({"email": email, "password": password})
    response = RedirectResponse("/admin/dashboard", status_code=303)
    response.set_cookie("admin_session", session.session.access_token, httponly=True, secure=True)
    return response
```

- Cookie-based session (httponly, secure) — no client-side JS token handling needed
  since this is server-rendered.
- Every admin route depends on `get_current_admin` via FastAPI `Depends()`.

### 4.2 Document management routes

```python
@router.get("/admin/documents", response_class=HTMLResponse)
async def list_documents(request: Request, admin=Depends(get_current_admin), supabase: SupabaseDep):
    docs = supabase.table("documents").select("*").order("updated_at", desc=True).execute()
    return templates.TemplateResponse("documents/list.html", {"request": request, "documents": docs.data})

@router.post("/admin/documents/upload")
async def upload_document(file: UploadFile, category: str = Form(...), title: str = Form(...),
                            admin=Depends(get_current_admin), supabase: SupabaseDep, qdrant: QdrantDep):
    # saves file temporarily, calls Module 4's process_and_index()
    tmp_path = await save_upload_temp(file)
    source_type = "pdf" if file.filename.endswith(".pdf") else "docx"
    result = await process_and_index(source_type, tmp_path, category, title, supabase, qdrant)
    await log_audit(supabase, admin["id"], "document_upload", "document", result.get("document_id"))
    return RedirectResponse("/admin/documents", status_code=303)

@router.post("/admin/documents/{document_id}/recrawl")
async def recrawl_url(document_id: str, admin=Depends(get_current_admin), supabase: SupabaseDep, qdrant: QdrantDep):
    doc = supabase.table("documents").select("*").eq("id", document_id).single().execute()
    result = await process_and_index("website", doc.data["source_url"], doc.data["category"],
                                        doc.data["title"], supabase, qdrant)
    await log_audit(supabase, admin["id"], "document_recrawl", "document", document_id)
    return RedirectResponse(f"/admin/documents/{document_id}", status_code=303)

@router.post("/admin/documents/{document_id}/deactivate")
async def deactivate_document(document_id: str, admin=Depends(get_current_admin), supabase: SupabaseDep, qdrant: QdrantDep):
    supabase.table("documents").update({"is_active": False}).eq("id", document_id).execute()
    qdrant.set_payload(collection_name="makkays_knowledge_base", payload={"is_active": False},
                         points_selector=Filter(must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]))
    await log_audit(supabase, admin["id"], "document_deactivate", "document", document_id)
    return RedirectResponse("/admin/documents", status_code=303)
```

- HTMX drives interactivity: upload form submits via `hx-post`, table rows swap via
  `hx-target` without full page reloads.

### 4.3 Conversation viewer

```python
@router.get("/admin/conversations", response_class=HTMLResponse)
async def list_conversations(request: Request, admin=Depends(get_current_admin), supabase: SupabaseDep):
    sessions = (supabase.table("chat_sessions").select("*, chat_messages(count)")
                .order("started_at", desc=True).limit(100).execute())
    return templates.TemplateResponse("conversations/list.html", {"request": request, "sessions": sessions.data})

@router.get("/admin/conversations/{session_id}", response_class=HTMLResponse)
async def conversation_detail(session_id: str, request: Request, admin=Depends(get_current_admin), supabase: SupabaseDep):
    messages = (supabase.table("chat_messages").select("*").eq("session_id", session_id)
                .order("created_at").execute())
    return templates.TemplateResponse("conversations/detail.html", {"request": request, "messages": messages.data})
```

- Show `confidence_score` and `retrieved_chunk_ids` inline per assistant message —
  valuable for debugging low-quality answers without a separate eval run.

### 4.4 Leads & tickets management

```python
@router.get("/admin/leads", response_class=HTMLResponse)
async def list_leads(request: Request, status: str | None = None, admin=Depends(get_current_admin), supabase: SupabaseDep):
    query = supabase.table("leads").select("*").order("created_at", desc=True)
    if status:
        query = query.eq("status", status)
    return templates.TemplateResponse("leads/list.html", {"request": request, "leads": query.execute().data})

@router.post("/admin/leads/{lead_id}/status")
async def update_lead_status(lead_id: str, status: str = Form(...), admin=Depends(get_current_admin), supabase: SupabaseDep):
    supabase.table("leads").update({"status": status}).eq("id", lead_id).execute()
    return RedirectResponse("/admin/leads", status_code=303)
```

- Same pattern for `support_tickets` (`admin/tickets`).

### 4.5 Unanswered questions & feedback views

- Read-only lists, sortable by `created_at` / `confidence_score` — this view is the
  primary input to Module 12's eval-set expansion (real gaps surface real questions
  to add to the eval suite) and to deciding what new content to ingest.
- Feedback view: aggregate thumbs up/down ratio at the top, individual comments below,
  linked back to the originating message/session.

### 4.6 Dashboard overview (`dashboard.html`)

- Simple stats: total conversations (7d/30d), total leads, open tickets count,
  average confidence score, thumbs up/down ratio. Basic counts via Supabase queries —
  no separate analytics service needed at this scale (full breakdown lives in Module
  10's "Analytics" sub-item, kept lightweight here).

### 4.7 Audit logging

```python
async def log_audit(supabase, admin_id, action, entity_type, entity_id, metadata=None):
    supabase.table("audit_logs").insert({
        "admin_id": admin_id, "action": action, "entity_type": entity_type,
        "entity_id": entity_id, "metadata": metadata or {},
    }).execute()
```

- Called from every mutating admin action (upload, recrawl, deactivate, status
  change) — this satisfies both this module's requirement and feeds Module 11's
  audit-trail guardrail requirement.

---

## 5. Testing & Validation Checklist

- [ ] Login with seeded admin credentials succeeds; wrong password fails cleanly.
- [ ] Accessing any `/admin/*` route without a valid session redirects to login.
- [ ] Document upload through the dashboard produces the same result as the
      Module 3/4 CLI-driven ingestion (spot check Qdrant point count).
- [ ] Recrawl on a changed URL creates a new version and updates the point set
      (ties to Module 4's incremental logic).
- [ ] Deactivating a document removes its chunks from live retrieval results
      (verify via a Module 5 test query before/after).
- [ ] Conversation detail view shows full transcript with confidence scores visible.
- [ ] Lead status update persists and reflects immediately in the filtered list.
- [ ] Every mutating action produces a corresponding `audit_logs` row.

---

## 6. Deliverable

A functioning, authenticated admin dashboard giving full visibility and control over
documents, conversations, leads, tickets, unanswered questions, and feedback — no
separate hosted service required.

---

## 7. Handoff Notes for Claude Code

- Keep this server-rendered (Jinja2+HTMX) per the project's stack decision — do not
  introduce a React SPA here; the project explicitly defers that to "later if the
  project gets budget."
- Reuse Module 3/4's `process_and_index()` and Module 4's deactivation logic exactly
  as-is from the admin upload/recrawl/deactivate routes — do not duplicate ingestion
  logic inside `admin.py`.
- This module is a natural place to violate the DI-thin-route pattern if not careful
  (HTML routes tend to accumulate logic) — keep query/mutation logic in small helper
  functions per section, mirroring `chat_service.py`'s pattern from Module 7.
