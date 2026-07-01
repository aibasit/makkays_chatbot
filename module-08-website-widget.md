# Module 8 — Website Widget

**Project:** Makkays AI Assistant (RAG Chatbot v4)
**Depends on:** Module 7 (Chat API)
**Blocks:** Widget embedding on the live site

---

## 1. Overview

A floating chat widget, embeddable on the Makkays website via a single `<script>` tag,
wired to `/api/chat`. Plain HTML/CSS/JS — no build step, no framework — so it can be
dropped into any page (WordPress, static HTML, whatever the live Makkays site runs on)
without a bundler.

---

## 2. Goals / Success Criteria

- One `<script src=".../makkays-chat-widget.js"></script>` tag renders a working
  floating chat bubble on any test page.
- Widget persists `session_id` and `visitor_id` across page reloads (localStorage),
  so returning to the site continues the same conversation.
- Conversation history renders correctly on reload.
- Matches Makkays branding (colors, logo, tone) rather than a generic chat UI.
- Works on both desktop and mobile viewports.

---

## 3. Folder/File Additions

```
widget/
├── makkays-chat-widget.js    # single-file vanilla JS widget
├── widget.css                  # scoped styles
└── embed-example.html           # test page for local development
```

---

## 4. Implementation Tasks

### 4.1 Embed contract

```html
<script src="https://<backend-host>/widget/makkays-chat-widget.js" data-api-base="https://<backend-host>"></script>
```

- `data-api-base` lets the same widget file point at different backend URLs
  (local dev vs. Render staging vs. Render production) without editing the file.

### 4.2 Widget shell (`makkays-chat-widget.js`)

- Self-invoking function, injects a `<div id="makkays-chat-widget-root">` and a
  `<link>` to `widget.css` (or inline `<style>` to avoid an extra network request —
  prefer inline given the small CSS footprint).
- No global namespace pollution beyond one `window.MakkaysChatWidget` object (mainly
  for debugging/future programmatic control, e.g. `MakkaysChatWidget.open()`).
- Floating bubble bottom-right (configurable), expands into a chat panel on click.

### 4.3 Session persistence

```javascript
function getOrCreateVisitorId() {
  let id = localStorage.getItem('makkays_visitor_id');
  if (!id) {
    id = crypto.randomUUID();
    localStorage.setItem('makkays_visitor_id', id);
  }
  return id;
}

function getStoredSessionId() {
  return localStorage.getItem('makkays_session_id');
}

function storeSessionId(sessionId) {
  localStorage.setItem('makkays_session_id', sessionId);
}
```

- On widget load, if a `session_id` exists, call
  `GET /api/chat/{session_id}/history` and render prior messages before the user
  sends anything new.

### 4.4 Sending messages

```javascript
async function sendMessage(text) {
  appendMessage('user', text);
  showTypingIndicator();

  const response = await fetch(`${apiBase}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: getStoredSessionId(),
      visitor_id: getOrCreateVisitorId(),
      message: text,
    }),
  });
  const data = await response.json();

  storeSessionId(data.session_id);
  hideTypingIndicator();
  appendMessage('assistant', data.answer);

  if (data.confidence_band === 'fallback') {
    maybeShowLeadCaptureForm();   // Module 9 hook
  }
}
```

- Handle Render's free-tier cold start (~30s first response after idle) with a
  visible "waking up, this may take a moment" state on the typing indicator if no
  response arrives within ~5 seconds — this is the one real trade-off in the stack,
  surface it gracefully rather than let it look broken.
- Handle `429` (rate limited, Module 7) with a friendly inline message, not a raw
  error.

### 4.5 UI/UX

- Message bubbles: user right-aligned, assistant left-aligned, timestamps optional.
- Typing indicator while awaiting response.
- Markdown-light rendering for assistant responses (bold, line breaks, bullet lists —
  Groq/Ollama may return markdown-formatted text) — a minimal regex-based renderer is
  sufficient, no need for a full markdown library in a dependency-free widget.
- Suggested-question chips on first open (e.g. "What power solutions do you offer?")
  to reduce blank-input friction.
- Close/minimize control that collapses back to the floating bubble without losing
  state.

### 4.6 Branding (`widget.css`)

- CSS custom properties at the top of the file for easy palette swap:

```css
:root {
  --makkays-primary: #0B5FA5;      /* replace with actual brand color */
  --makkays-accent: #F2A900;
  --makkays-bg: #FFFFFF;
  --makkays-text: #1A1A1A;
  --makkays-radius: 12px;
}
```

- Use the actual Makkays logo (small icon) in the bubble/header, not a generic chat
  icon.
- All widget styles scoped under `#makkays-chat-widget-root` to avoid leaking into
  or being overridden by the host page's CSS.

### 4.7 Mobile responsiveness

- Below ~480px viewport width, chat panel expands to near-fullscreen rather than a
  fixed small popup — standard mobile chat widget pattern.
- Touch-friendly tap targets (min 44px) for send button, suggested chips, close
  button.

---

## 5. Testing & Validation Checklist

- [ ] Widget renders correctly when embedded via a single `<script>` tag on a plain
      test HTML page (`embed-example.html`).
- [ ] Sending a message returns and renders an assistant response end-to-end against
      the real `/api/chat` backend.
- [ ] Reloading the page preserves `session_id`/`visitor_id` and re-renders prior
      history.
- [ ] Widget doesn't visually break or conflict with a host page that has its own
      global CSS (test on a page with aggressive global styles like `* { margin: 0 }`
      resets or a CSS framework).
- [ ] Cold-start delay is handled gracefully with a "waking up" state, not a silent
      hang.
- [ ] Mobile viewport (real device or dev-tools emulation) — panel is usable, no
      overflow/clipping.
- [ ] Branding colors/logo match Makkays' actual site identity (confirm with
      whatever brand assets are available).

---

## 6. Deliverable

A working, branded chat bubble embeddable on a test page via one `<script>` tag,
fully wired to the live `/api/chat` backend, with session persistence and graceful
handling of cold starts and rate limits.

---

## 7. Handoff Notes for Claude Code

- Keep this dependency-free (no React/build step) — the project's stack explicitly
  chose "just HTML/CSS/JS" for the widget; don't introduce a bundler unless a future
  module explicitly calls for one.
- Leave a clear, minimal hook point for Module 9's lead-capture form to render inside
  the widget on `fallback`-band responses — don't build the lead form itself here,
  just the mount point/callback.
- If hosting the widget file separately (Vercel/Netlify per the project's stack table)
  rather than serving it as a static file from FastAPI, make sure CORS on the backend
  (Module 1's `CORS_ORIGINS`) includes that hosting domain.
