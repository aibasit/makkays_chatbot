# Module 9 — Lead & Support System

**Project:** Makkays AI Assistant (RAG Chatbot v4)
**Depends on:** Module 7 (Chat API), Module 2 (Supabase — `leads`/`support_tickets`
tables)
**Blocks:** Module 10 (Admin Dashboard — surfaces this data), Module 12 (eval includes
this flow)

---

## 1. Overview

This module turns chat conversations into business outcomes: detecting buying intent
and prompting for contact details, capturing structured leads, and — when the bot
can't answer a question (Module 5's `fallback` confidence band) — collecting contact
info and emailing the support team so no question goes unanswered silently.

---

## 2. Goals / Success Criteria

- Buying-intent messages (e.g. "how much does the UPS cost", "I want a quote") trigger
  an in-chat lead capture form, correctly categorized against the project's existing
  taxonomy.
- Captured leads are stored in Supabase `leads` with correct category, linked to the
  originating `chat_session`.
- Low-confidence (`fallback` band) queries offer contact capture and, once submitted,
  create a `support_tickets` row and send a real email via Resend (or SMTP fallback).
- Every unanswerable question is logged to `unanswered_questions` regardless of
  whether the visitor provides contact info — so Module 10's admin view and Module
  12's eval have visibility into gaps even from anonymous visitors who don't convert.

---

## 3. Folder/File Additions

```
backend/app/
├── api/
│   └── leads.py                # POST endpoints for lead + ticket submission
└── services/
    ├── lead_service.py           # intent detection, lead persistence
    └── email_service.py           # Resend / SMTP sending
```

---

## 4. Implementation Tasks

### 4.1 Intent detection (`lead_service.py`)

- Lightweight approach appropriate to this scale: a short Groq call (same
  `LLMRouter` from Module 6) classifying the latest message + recent context into
  one of: `buying_intent`, `support_request`, `general_question`, `none`.

```python
INTENT_CLASSIFICATION_PROMPT = """Classify the visitor's latest message into exactly
one category: buying_intent, support_request, general_question, none.
Respond with only the category word, nothing else.

Recent conversation:
{history}

Latest message: {message}
"""

async def detect_intent(message: str, history: list[dict], llm_router) -> str:
    prompt = INTENT_CLASSIFICATION_PROMPT.format(
        history="\n".join(f"{h['role']}: {h['content']}" for h in history[-4:]),
        message=message,
    )
    result, _ = await llm_router.generate("", [{"role": "user", "content": prompt}], max_tokens=10)
    category = result.strip().lower()
    return category if category in {"buying_intent", "support_request", "general_question", "none"} else "none"
```

- Called from Module 7's `handle_chat_message` alongside (not instead of) the main
  RAG pipeline — intent detection and answer generation are independent concerns;
  don't block the answer on intent classification, run them and merge results.
- Category mapping to the lead taxonomy (`Power / Business Automation / Test &
  Measurement / Services & Support / General Inquiry`) can reuse the same
  category-tagging already present on retrieved chunks' `category` payload field
  (Module 4) as a strong signal, combined with the LLM classification.

### 4.2 Lead capture flow

```python
class LeadCaptureRequest(BaseModel):
    session_id: str
    name: str
    email: str
    phone: str | None = None
    category: str
    message: str | None = None

async def create_lead(supabase, request: LeadCaptureRequest) -> dict:
    result = supabase.table("leads").insert({
        "session_id": request.session_id,
        "name": request.name,
        "email": request.email,
        "phone": request.phone,
        "category": request.category,
        "message": request.message,
        "status": "new",
    }).execute()
    return result.data[0]
```

- Widget-side: on `buying_intent` detection, Module 8's widget renders a small inline
  form (name, email, phone optional, pre-filled category if inferable) rather than
  interrupting the chat flow with a modal.
- On submission, `POST /api/leads` persists and triggers an internal notification
  email (not the visitor-facing fallback email from §4.3 — this is a "new lead"
  alert to the sales team).

### 4.3 Fallback → support ticket + email handoff

```python
class TicketRequest(BaseModel):
    session_id: str
    contact_email: str
    original_question: str

async def create_support_ticket(supabase, request: TicketRequest) -> dict:
    result = supabase.table("support_tickets").insert({
        "session_id": request.session_id,
        "subject": f"Unanswered question: {request.original_question[:80]}",
        "description": request.original_question,
        "contact_email": request.contact_email,
        "status": "open",
    }).execute()
    return result.data[0]
```

- Every `fallback`-band answer (from Module 7) also writes to `unanswered_questions`
  immediately, **independent of** whether the visitor submits contact info — this
  logging must not depend on conversion.

```python
async def log_unanswered_question(supabase, session_id, question, confidence_score):
    supabase.table("unanswered_questions").insert({
        "session_id": session_id, "question": question, "confidence_score": confidence_score,
    }).execute()
```

### 4.4 Email notifications (`email_service.py`)

- Primary: Resend.com free tier (100 emails/day). Fallback: Gmail SMTP (zero-signup).

```python
import resend
from app.config import get_settings

async def send_email_resend(to: str, subject: str, html_body: str) -> bool:
    settings = get_settings()
    resend.api_key = settings.resend_api_key
    try:
        resend.Emails.send({
            "from": "Makkays Assistant <notifications@makkays.com>",
            "to": to, "subject": subject, "html": html_body,
        })
        return True
    except Exception:
        return False

async def send_email_smtp_fallback(to: str, subject: str, html_body: str) -> bool:
    import smtplib
    from email.mime.text import MIMEText
    settings = get_settings()
    msg = MIMEText(html_body, "html")
    msg["Subject"], msg["From"], msg["To"] = subject, settings.smtp_user, to
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
        return True
    except Exception:
        return False

async def send_notification(to: str, subject: str, html_body: str) -> bool:
    if await send_email_resend(to, subject, html_body):
        return True
    return await send_email_smtp_fallback(to, subject, html_body)
```

- New lead → email to sales team address.
- New support ticket → email to support team address, containing the original
  question and visitor contact info.
- Keep templates simple inline HTML strings — no templating engine needed for 2–3
  email types at this scale.

### 4.5 Routes (`api/leads.py`)

```python
@router.post("/api/leads")
async def submit_lead(request: LeadCaptureRequest, supabase: SupabaseDep):
    lead = await create_lead(supabase, request)
    await send_notification(SALES_EMAIL, f"New lead: {request.category}", render_lead_email(lead))
    return lead

@router.post("/api/support-tickets")
async def submit_ticket(request: TicketRequest, supabase: SupabaseDep):
    ticket = await create_support_ticket(supabase, request)
    await send_notification(SUPPORT_EMAIL, "Unanswered question needs follow-up", render_ticket_email(ticket))
    return ticket
```

---

## 5. Testing & Validation Checklist

- [ ] A clearly buying-intent message ("what's the price of X") triggers
      `buying_intent` classification.
- [ ] A clearly unrelated message ("what's the weather") classifies as `none`.
- [ ] Submitting a lead form creates a correct `leads` row and sends a real email
      (verify inbox receipt, not just a 200 response).
- [ ] A `fallback`-band chat response writes to `unanswered_questions` even if the
      visitor never submits a support ticket.
- [ ] Submitting a support ticket after a fallback response creates a correct
      `support_tickets` row and sends a real email to the support address.
- [ ] Resend failure (e.g. temporarily invalid API key) correctly falls back to SMTP
      and still delivers the email.
- [ ] Lead category values are always one of the five valid taxonomy values — no
      free-text categories leak through.

---

## 6. Deliverable

Buying-intent chats capture and store contact details with real email notification;
unanswerable questions are logged unconditionally and produce a real support email on
follow-up submission.

---

## 7. Handoff Notes for Claude Code

- Keep intent detection non-blocking relative to the main answer — a slow or failed
  intent classification should never delay or break the chat response itself; fail
  soft to `"none"` on any error.
- Resend's 100 emails/day free-tier cap is realistic for this project's traffic, but
  if it's ever approached, that's an operational monitoring concern — the
  SMTP fallback already provides headroom, don't add complexity here.
- `unanswered_questions` logging must happen from Module 7's orchestration point
  (fallback branch) unconditionally — do not make it depend on this module's routes
  being called, since most low-confidence visitors will never fill out the ticket
  form and that data is still valuable for Module 12's eval.
