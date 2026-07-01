# Makkays AI Assistant — Module Handoff Docs

Grand build plan for the RAG chatbot (v4 stack: FastAPI, Supabase, Qdrant Cloud,
Upstash Redis, self-hosted BGE-M3 + `bge-reranker-large`, Groq primary / Ollama
fallback). Each module is a standalone, Claude-Code-ready handoff `.md` file: goals,
folder structure, implementation-ready code, schemas, a testing checklist, and
handoff notes for whoever (or whichever Claude Code session) builds it next.

Build strictly in order — each module states its explicit dependencies, and later
modules assume earlier ones are done.

| # | Module | File |
|---|---|---|
| 1 | Project Foundation | `module-01-project-foundation.md` |
| 2 | Database & Infrastructure | `module-02-database-infrastructure.md` |
| 3 | Document Ingestion Pipeline | `module-03-document-ingestion.md` |
| 4 | Embedding & Indexing | `module-04-embedding-indexing.md` |
| 5 | Retrieval Engine (RAG Core) | `module-05-retrieval-engine.md` |
| 6 | LLM Integration | `module-06-llm-integration.md` |
| 7 | Chat API | `module-07-chat-api.md` |
| 8 | Website Widget | `module-08-website-widget.md` |
| 9 | Lead & Support System | `module-09-lead-support-system.md` |
| 10 | Admin Dashboard | `module-10-admin-dashboard.md` |
| 11 | Security & Guardrails | `module-11-security-guardrails.md` |
| 12 | Testing & Evaluation | `module-12-testing-evaluation.md` |

## Dependency chain

```
1 Foundation
   └─▶ 2 Database & Infrastructure
          └─▶ 3 Ingestion ─▶ 4 Embedding & Indexing ─▶ 5 Retrieval Engine
                                                            └─▶ 6 LLM Integration
                                                                   └─▶ 7 Chat API
                                                                          ├─▶ 8 Widget
                                                                          └─▶ 9 Lead & Support
                                                                                 └─▶ 10 Admin Dashboard
11 Security & Guardrails  (cross-cutting — touches 3, 6, 7, 9, 10)
12 Testing & Evaluation   (depends on 5, 6, 11)
```

## Reference

Source spec this plan implements: `makkays-rag-chatbot-v4-free-tier-real-tools.md`
(the $0-budget, free-tier-real-tools v4 stack correction from the DIY-substitute v3).
