# AI Sales Engineer — Complete System Flowchart (v4.2)

---

## 1. Top-Level Architecture: Request Lifecycle

```mermaid
flowchart TD
    USER(["👤 End User"])

    subgraph FE["M17 — Frontend Widget (React/TS/Vite)"]
        WIDGET["Chat Widget UI\n• Accept-Language header\n• Session cookie\n• Message input"]
    end

    subgraph M15["M15 — Public API (FastAPI)"]
        direction TB
        API_IN["Receive HTTP Request"]
        API_AUTH{"Valid Site\nAPI Key?"}
        API_COOKIE["Issue / Reuse\nSession Cookie"]
        API_RATE{"Rate Limit\n20 req/min OK?"}
        API_LANG["Parse Accept-Language\nheader → language hint"]
        API_ERR1["401 Unauthorized"]
        API_ERR2["429 Too Many Requests"]
    end

    subgraph ORCH_BOX["M06 — Orchestrator"]
        ORCH["on_turn(tenant_id, session_id, message)"]
    end

    subgraph RESP_BOX["M15 — Response Assembly"]
        API_RESP["Build ChatResponse\n• assistant_message\n• session_id\n• awaiting_clarification"]
    end

    USER -->|"Types message"| WIDGET
    WIDGET -->|"POST /chat"| API_IN
    API_IN --> API_AUTH
    API_AUTH -->|"No"| API_ERR1
    API_AUTH -->|"Yes"| API_COOKIE
    API_COOKIE --> API_RATE
    API_RATE -->|"No"| API_ERR2
    API_RATE -->|"Yes"| API_LANG
    API_LANG --> ORCH
    ORCH -->|"OrchestratorResult"| API_RESP
    API_RESP -->|"JSON Response"| WIDGET
    WIDGET -->|"Displays reply"| USER
```

---

## 2. Orchestrator Turn Flow (M06)

```mermaid
flowchart TD
    START(["on_turn START"])

    subgraph LOAD["Step 1-2: Load Session Data (M03 + M04)"]
        L1["SessionStateService.get_facts()"]
        L2["SessionStateService.get_conversation_state()"]
        L3["TurnsService.get_recent_turns(limit=8)"]
        L1 --> L2 --> L3
    end

    subgraph LANG_DET["Step 2a: Language Detection (M21)"]
        LD{"enable_multi_language\n= true?"}
        LD_RUN["LanguageDetectionService.detect(message)"]
        LD_SAVE["Update conversation_state.language_code"]
        LD -->|"Yes"| LD_RUN --> LD_SAVE
        LD -->|"No"| LD_SKIP["Skip"]
    end

    subgraph FACTS["Step 3: Facts Extraction (M06)"]
        FE["FactsExtractor.extract(message, facts, state, turns)"]
        FE_SAVE["SessionStateService.update_facts(patch)"]
        FE --> FE_SAVE
    end

    subgraph FLAGS["Step 4: Feature Flags (M09)"]
        FF["FeatureFlagsService.resolve(tenant_id)\n• 60-sec TTL cache\n• DB overrides > env defaults"]
    end

    subgraph ROUTE["Step 5: Intent Classification (M06 Router)"]
        ROUTER["Router.classify(message, facts, state, turns)"]
    end

    subgraph METRICS["Step 6: Metrics (M16)"]
        M_INC["MetricsRegistry.increment_intent_classification()\nMetricsRegistry.record_intent_confidence()"]
    end

    subgraph STATE_WRITE["Step 7: Persist Intent"]
        SW["ConversationStateRepository.upsert(intent, confidence)"]
    end

    subgraph CONF_GATE["Step 8-9: Confidence Gate"]
        CONF{"confidence >=\nthreshold (0.7)?"}
        CLAR_PATH["→ Clarification Flow (M13)"]
        PLAN_PATH["→ Task Planner (M07)"]
        MAX_CLAR{"MaxClarification\nRoundsExceeded?"}
        ESCALATE["Override intent =\n'escalation_request'"]
    end

    subgraph TURN_NUM["Step 8: Turn Number"]
        TN["TurnsService.get_next_turn_number()"]
    end

    START --> LOAD --> LANG_DET --> FACTS --> FLAGS --> ROUTE --> METRICS --> STATE_WRITE --> CONF_GATE
    STATE_WRITE --> TN

    CONF -->|"No"| CLAR_PATH
    CLAR_PATH --> MAX_CLAR
    MAX_CLAR -->|"Yes"| ESCALATE --> PLAN_PATH
    MAX_CLAR -->|"No"| CLAR_RESP(["Return clarification\nquestion to user"])
    CONF -->|"Yes"| PLAN_PATH
```

---

## 3. Intent Classification: Tier 1 + Tier 2 (M06 Router)

```mermaid
flowchart TD
    MSG(["User Message"])

    subgraph T1["Tier 1 — Rule Engine (app/router/rules.py)"]
        T1_MATCH{"Tier1RuleEngine\n.match(message)"}
        T1_AMBI{"Multiple rule\nsets match?"}
        T1_HIT["Return IntentResult\n(confidence=1.0, source='tier1')"]
    end

    subgraph T2["Tier 2 — LLM Classifier (app/router/classifier.py)"]
        T2_BUILD["Build classify_intent\nLLM tool call prompt"]
        T2_LLM["LLMClientProtocol.chat()\n→ Qwen2.5:3b\n(Ollama, local)"]
        T2_PARSE["Parse structured output\n{ intent, confidence, candidates }"]
        T2_VALID{"intent in\ntaxonomy?\nconfidence in [0,1]?"}
        T2_CLAMP["Clamp / reject\n→ treat as 0.0 confidence"]
        T2_RESULT["Return IntentResult\n(source='tier2')"]
    end

    MSG --> T1_MATCH
    T1_MATCH -->|"No match"| T2_BUILD
    T1_MATCH -->|"Match"| T1_AMBI
    T1_AMBI -->|"Ambiguous"| T2_BUILD
    T1_AMBI -->|"Unambiguous"| T1_HIT

    T2_BUILD --> T2_LLM --> T2_PARSE --> T2_VALID
    T2_VALID -->|"Invalid"| T2_CLAMP
    T2_VALID -->|"Valid"| T2_RESULT
```

**Full Intent Taxonomy (v4.1 + v4.2):**

| Group | Intents |
|---|---|
| **Sales** | `sales_inquiry`, `quote_request` |
| **Support** | `technical_support`, `troubleshooting`, `installation_guidance`, `warranty_information` |
| **Product Intelligence** | `product_comparison`, `product_compatibility`, `accessory_recommendation`, `product_finder_by_problem`, `product_alternative`, `specification_explainer` |
| **Discovery** | `product_recommendation_wizard`, `use_case_recommendation`, `pdf_documentation_search` |
| **Transactional** | `availability_inquiry`, `solution_builder`, `human_handoff`, `escalation_request` |
| **System** | `out_of_scope` |

---

## 4. Task Planner → Tool Executor (M07 + M10)

```mermaid
flowchart TD
    INTENT(["IntentResult"])

    subgraph M07["M07 — Task Planner (app/planner/rules.py)"]
        P_REG{"RULES registry\nlookup(intent)"}
        P_UNKNOWN["Raise UnknownIntentError\n→ fallback: escalation_request"]
        P_FN["rule_fn(facts, state, flags, intent_result)"]
        P_CHECK{"steps list\nempty?"}
        P_FALLBACK["Substitute: ['respond']"]
        P_PLAN["Return Plan(intent, steps)"]
    end

    subgraph PERSIST_PLAN["M06 — Persist Plan"]
        PP["SessionStateService.update_conversation_state\n(current_plan, current_plan_step=0)"]
    end

    subgraph M10["M10 — Tool Executor + Security Policy"]
        TE_LOOP["For each step in plan.steps"]
        TE_POLICY{"SecurityPolicy\n.is_allowed(step, session, flags)?"}
        TE_DENY["Skip step\nLog WARNING"]
        TE_EXEC["Execute tool function\n→ ToolExecutionResult"]
        TE_CTX["Update ExecutionContext\n(carry results between steps)"]
    end

    INTENT --> P_REG
    P_REG -->|"Not found"| P_UNKNOWN
    P_REG -->|"Found"| P_FN
    P_FN --> P_CHECK
    P_CHECK -->|"Empty (bug)"| P_FALLBACK
    P_CHECK -->|"Non-empty"| P_PLAN
    P_PLAN --> PERSIST_PLAN --> M10

    TE_LOOP --> TE_POLICY
    TE_POLICY -->|"Denied"| TE_DENY --> TE_LOOP
    TE_POLICY -->|"Allowed"| TE_EXEC --> TE_CTX --> TE_LOOP
```

---

## 5. Tool Execution Map — All 17 Tool Steps

```mermaid
flowchart LR
    EXEC(["Tool Executor\nexecute_plan()"])

    subgraph RAG["M11 — RAG Engine"]
        T_RP["retrieve_products\n• FilterExtractor → SQL narrow\n• Qdrant vector search\n• BGE-M3 embeddings"]
        T_RD["retrieve_docs\n• doc_type filter\n• Qdrant documents_v1\n• intent→doc_type mapping"]
    end

    subgraph INTEL["M18 — Product Intelligence"]
        T_CP["compare_products\n• ProductSpecRepository\n• Comparison table\n• LLM summary (narration only)"]
        T_CC["check_compatibility\n• CompatibilityRepository\n• Rule → LLM fallback inference"]
        T_RA["recommend_accessories\n• AccessoryRepository\n• Vector similarity supplement"]
        T_FA["find_alternatives\n• Same-category SQL\n• Qdrant re-rank"]
        T_ES["explain_specification\n• LLM explanation\n• Doc context grounding"]
    end

    subgraph SOL["M19 — Solution Builder"]
        T_WIZ["run_wizard\n• WizardService.advance()\n• 4-step requirement collection (no budget)\n• ScaleClassifier auto-detects scale\n• Calculated or Call-For-Pricing\n• Persists to wizard_sessions"]
        T_UC["build_use_case_solution\n• UseCaseService\n• Pre-defined profiles (7)\n• BOMService.build()"]
        T_BS["build_solution\n• BOMService.build()\n• Deterministic pricing\n• SolutionExplainer (LLM narration)"]
    end

    subgraph QUOTE["M12 — Quote Builder"]
        T_GQ["generate_quote\n• QuoteBuilder (SQL pricing)\n• QuoteExplainer (LLM narration)\n• QuotePDFGenerator (reportlab)\n• Email PDF via Resend"]
        T_MS["request_missing_slots\n• Ask for missing\n  company/product/qty/budget"]
    end

    subgraph CRM["M14 — CRM + Email"]
        T_CL["create_lead\n• LeadService.create_lead()\n• Extended qualification fields\n• Retry queue → CRM sync\n• Email notification (Resend)"]
    end

    subgraph HANDOFF["M20 — Human Handoff"]
        T_IH["initiate_handoff\n• Export conversation (50 turns)\n• Create handoff_requests record\n• Email team (fire-and-forget)\n• Return reference ID"]
    end

    subgraph AVAIL["M22 — Availability"]
        T_CA["check_availability\n• LocalAvailabilityService\n  (or ERPAvailabilityService stub)\n• product_availability table"]
    end

    subgraph RESPOND["M05 — LLM Engine"]
        T_RS["respond\n• Assemble final message\n• LLM builds natural language reply\n• Uses tool results from ExecutionContext"]
    end

    EXEC --> T_RP & T_RD & T_CP & T_CC & T_RA & T_FA & T_ES
    EXEC --> T_WIZ & T_UC & T_BS
    EXEC --> T_GQ & T_MS
    EXEC --> T_CL
    EXEC --> T_IH
    EXEC --> T_CA
    EXEC --> T_RS
```

---

## 6. RAG Engine Pipeline (M11)

```mermaid
flowchart TD
    QUERY(["User query / product_interest"])

    subgraph FILTER["Filter Extraction"]
        FX["FilterExtractor.extract(query, tenant_id)\n• Keyword match vs. brand/category vocab\n• Populates ExtractedFilters\n  { brand, category, spec_filters, doc_type, use_case }"]
    end

    subgraph SQL_NARROW["SQL Narrowing (PostgreSQL)"]
        SQL["ProductRepository.find_by_filters()\nor DocumentRepository.find_by_type()\n→ candidate_ids: list[UUID]"]
    end

    subgraph EMBED["Embedding (BGE-M3)"]
        EMB["BgeM3Embedder.embed([query])\n→ 1024-dim dense vector\n(run_in_executor — non-blocking)"]
    end

    subgraph QDRANT["Qdrant Cloud Search"]
        QS["QdrantWrapper.search()\ncollection: products_v1 / documents_v1\nfilter: tenant_id + candidate_ids + doc_type\nlimit: RAG_SEARCH_LIMIT_DEFAULT"]
    end

    subgraph RESULT["Result Mapping"]
        RM["ScoredPoint → ProductResult / DocResult\nMetricsRegistry.increment_rag_hit()"]
    end

    QUERY --> FILTER --> SQL_NARROW --> EMBED --> QDRANT --> RESULT
```

---

## 7. Multi-turn Wizard Flow (M19)

```mermaid
flowchart TD
    WT1(["Turn 1: 'Help me build a network setup'"])
    WT2(["Turn 2: User answers use_case"])
    WT3(["Turn 3: User answers device_count"])
    WT4(["Turn 4: User answers location"])
    WT5(["Turn 5: User answers brand_preference (optional)"])

    subgraph WS["WizardService.advance() — each turn"]
        WS_LOAD["Load WizardSession from DB\n(wizard_sessions table)"]
        WS_SAVE["Save answer to collected_requirements JSONB"]
        WS_CLASSIFY["ScaleClassifier.classify(device_count, use_case)\n→ ProjectScale (size, pricing_mode)"]
        WS_STEP{"All 4 slots\nfilled?"}
        WS_NEXT["Return next question\n(WizardStep.is_complete=False)"]
        
        WS_MODE{"pricing_mode?"}
        WS_BOM["BOMService.build(requirements)\n→ Deterministic pricing from product_pricing"]
        WS_NARR["SolutionExplainer.explain(solution, llm_client)\n→ LLM narrates only"]
        WS_DONE["Return WizardStep(is_complete=True, solution=...)"]
        
        WS_CFP["CallForPricingService.handle()\n• Create CRM lead\n• Email sales team\n• Generate priority reference ID"]
        WS_CFP_DONE["Return WizardStep(is_complete=True, call_for_pricing=...)"]
    end

    WT1 --> WS_LOAD --> WS_SAVE --> WS_STEP
    WT2 --> WS_LOAD
    WT3 --> WS_LOAD --> WS_CLASSIFY
    WT4 --> WS_LOAD
    WT5 --> WS_LOAD

    WS_STEP -->|"No"| WS_NEXT
    WS_STEP -->|"Yes"| WS_MODE
    WS_MODE -->|"calculated"| WS_BOM --> WS_NARR --> WS_DONE
    WS_MODE -->|"call_for_pricing"| WS_CFP --> WS_CFP_DONE
```

---

## 8. Human Handoff Flow (M20)

```mermaid
flowchart TD
    HU(["User: 'Connect me to sales'"])

    T1_HH["Tier 1: 'talk to' / 'connect me' → human_handoff"]
    CLAR_HH["Clarification: handoff_type_selection.md\n→ Sales / Technical / Support?"]
    USER_SEL["User selects: Sales Team"]
    PLAN_HH["Planner: ['initiate_handoff', 'respond']"]

    subgraph HS["HandoffService.initiate()"]
        HS_CHECK{"Active handoff\nalready exists?"}
        HS_EXIST["Return existing\nreference ID"]
        HS_EXPORT["TurnsService.get_recent_turns(limit=50)\n→ conversation_export JSONB"]
        HS_DB["HandoffRepository.create()\n→ handoff_requests table\n  status='pending'"]
        HS_EMAIL["asyncio.create_task(\n  NotificationService.send_handoff_notification()\n)\n→ Resend email to team"]
        HS_RESULT["Return HandoffResult\n{ handoff_id, reference_id='HO-20260703-001' }"]
    end

    RESPOND_HH["respond: 'I've connected you to Sales.\nReference: HO-20260703-001.\nSomeone will contact you shortly.'"]

    HU --> T1_HH --> CLAR_HH --> USER_SEL --> PLAN_HH
    PLAN_HH --> HS_CHECK
    HS_CHECK -->|"Yes"| HS_EXIST
    HS_CHECK -->|"No"| HS_EXPORT --> HS_DB --> HS_EMAIL --> HS_RESULT
    HS_RESULT --> RESPOND_HH
```

---

## 9. Multi-language Pipeline (M21)

```mermaid
flowchart LR
    MSG_IN(["User message\n(any language)"])

    subgraph DET["Language Detection"]
        LD["LanguageDetectionService.detect(message)\n(langdetect library)\n→ 'en' | 'ur' | 'ar'"]
        LD_SAVE["Update conversation_state.language_code"]
    end

    subgraph PROCESS["Full Turn Processing\n(all in English)"]
        P1["Facts extraction"]
        P2["Intent classification"]
        P3["RAG retrieval"]
        P4["Tool execution"]
        P5["Response assembly (English)"]
    end

    subgraph TRANSLATE["Response Translation"]
        TR_CHECK{"language_code\n!= 'en'?"}
        TR_RUN["TranslationService.translate(\n  text=english_response,\n  target='ur' or 'ar',\n  llm_client=qwen2.5:3b\n)"]
        TR_FAIL{"LLM\nfailed?"}
        TR_ORIG["Return original\nEnglish response"]
        TR_OUT["Translated response"]
    end

    RESP_OUT(["Response in user's language"])

    MSG_IN --> DET --> LD_SAVE
    LD_SAVE --> PROCESS
    PROCESS --> TR_CHECK
    TR_CHECK -->|"Yes"| TR_RUN --> TR_FAIL
    TR_CHECK -->|"No (already English)"| RESP_OUT
    TR_FAIL -->|"Yes"| TR_ORIG --> RESP_OUT
    TR_FAIL -->|"No"| TR_OUT --> RESP_OUT
```

---

## 10. Storage Systems Map

```mermaid
flowchart TD
    subgraph PG["PostgreSQL — Supabase"]
        direction LR
        subgraph CORE_TABLES["Core"]
            T_SESS["session_facts\n(contact, company, product_interest,\nindustry, location, timeline...)"]
            T_STATE["conversation_state\n(intent, plan, language_code,\ncontact_info_captured...)"]
            T_TURNS["conversation_turns\n(full message history, tool results)"]
        end
        subgraph PRODUCT_TABLES["Product Catalog"]
            T_PROD["products\n(id, name, brand, category)"]
            T_SPEC["product_specs\n(product_id, spec_key, spec_value)"]
            T_PRICE["product_pricing\n(product_id, unit_price, currency)"]
            T_AVAIL["product_availability\n(product_id, quantity, delivery_days)"]
        end
        subgraph DOC_TABLES["Documents"]
            T_DOCS["documents\n(id, title, source_path, document_type)"]
        end
        subgraph INTEL_TABLES["Intelligence"]
            T_COMPAT["compatibility_rules\n(primary_id, secondary_id, type, is_compatible)"]
            T_ACCESSORY["accessory_relations\n(primary_id, accessory_id, relation_type)"]
        end
        subgraph SOL_TABLES["Solution Builder"]
            T_WIZ_S["wizard_sessions\n(session_id, current_step, requirements, completed)"]
            T_USE_CASE["use_case_profiles\n(use_case, requirements JSONB)"]
            T_SOLUTION["solutions\n(requirements, line_items, total_estimate)"]
        end
        subgraph CRM_TABLES["CRM & Handoff"]
            T_LEADS["leads\n(contact info, product_interest, qualification)"]
            T_RETRY["retry_queue\n(lead_id, attempts, next_retry_at)"]
            T_QUOTES["quotes\n(line_items, total, pdf_bytes)"]
            T_HANDOFF["handoff_requests\n(target_team, status, conversation_export)"]
        end
        subgraph SYS_TABLES["System"]
            T_FLAGS["feature_flags\n(tenant_id, flag_name, enabled)"]
        end
    end

    subgraph REDIS["Redis"]
        R1["conversation:state:{tenant}:{session}\n(ConversationState, TTL=1800s)"]
        R2["conversation:facts:{tenant}:{session}\n(SessionFacts, TTL=1800s)"]
        R3["rate_limit:{api_key}:{window}\n(request counter, TTL=60s)"]
    end

    subgraph QDRANT["Qdrant Cloud (us-east-2)"]
        Q1["products_v1\n(1024-dim COSINE, BGE-M3)\npayload: tenant_id, product_id, brand, category"]
        Q2["documents_v1\n(1024-dim COSINE, BGE-M3)\npayload: tenant_id, document_id, product_id, document_type"]
    end
```

---

## 11. External Services & Infrastructure

```mermaid
flowchart LR
    subgraph LOCAL["Local Machine"]
        APP["FastAPI App\n(uvicorn)"]
        LLM_LOCAL["Ollama\n(qwen2.5:3b)\nTool-calling loop\nM05"]
        BGE["BGE-M3 Model\n(FlagEmbedding)\n1024-dim embeddings\nM11"]
    end

    subgraph CLOUD["Cloud Services"]
        SUPABASE["Supabase\n(PostgreSQL)\nAll persistent data"]
        REDIS_CLOUD["Redis\n(local or cloud)\nSession cache"]
        QDRANT_CLOUD["Qdrant Cloud\n(us-east-2)\nVector search"]
        RESEND["Resend API\nEmail delivery\n(leads, quotes, handoffs)"]
    end

    APP -->|"asyncpg / SQLAlchemy async"| SUPABASE
    APP -->|"redis.asyncio"| REDIS_CLOUD
    APP -->|"qdrant-client (sync + executor)"| QDRANT_CLOUD
    APP -->|"HTTP REST"| LLM_LOCAL
    APP -->|"run_in_executor"| BGE
    APP -->|"HTTPS (Resend SDK)"| RESEND

    CRM_EXT["External CRM\n(Future: AVAILABILITY_PROVIDER=erp)"]
    APP -.->|"ERPAvailabilityService stub\n(NotImplementedError)"| CRM_EXT
```

---

## 12. Complete Turn Sequence (Happy Path — Quote Request)

```mermaid
sequenceDiagram
    actor User
    participant Widget as M17 Widget
    participant API as M15 API
    participant Orch as M06 Orchestrator
    participant Router as M06 Router
    participant Planner as M07 Planner
    participant Executor as M10 Tool Executor
    participant RAG as M11 RAG Engine
    participant Quote as M12 Quote Builder
    participant CRM as M14 CRM
    participant LLM as M05 LLM (Qwen)
    participant DB as PostgreSQL
    participant Redis as Redis
    participant Qdrant as Qdrant

    User->>Widget: "I need 10 X200 switches for ABC Corp, budget $5000"
    Widget->>API: POST /chat {message, session_cookie}
    API->>API: Auth + Rate limit check
    API->>Orch: on_turn(tenant_id, session_id, message)

    Orch->>Redis: get_facts() + get_conversation_state()
    Orch->>DB: get_recent_turns(limit=8)
    Orch->>LLM: FactsExtractor.extract() → {company, quantity, budget}
    Orch->>Redis: update_facts(patch)
    Orch->>DB: FeatureFlagsService.resolve()

    Orch->>Router: classify(message, facts, state)
    Router->>Router: Tier1: "how much" ambiguous → fallthrough
    Router->>LLM: classify_intent tool call
    LLM-->>Router: {intent: "quote_request", confidence: 0.91}
    Router-->>Orch: IntentResult(intent="quote_request", confidence=0.91)

    Orch->>DB: upsert conversation_state(intent, confidence)
    Note over Orch: confidence 0.91 >= 0.70 threshold → Plan

    Orch->>Planner: build_plan(quote_request, facts, state, flags)
    Note over Planner: quote_slots_complete(facts)=True, enable_quotes=True
    Planner-->>Orch: Plan(steps=["retrieve_products","generate_quote","create_lead","respond"])

    Orch->>Executor: execute_plan(plan, session_context, flags)

    Executor->>RAG: retrieve_products(session, context)
    RAG->>Qdrant: vector search "X200 switch"
    Qdrant-->>RAG: [ProductResult(X200, score=0.94)]
    RAG-->>Executor: ToolExecutionResult(product_ids=[X200_id])

    Executor->>Quote: generate_quote(session, context)
    Quote->>DB: ProductPricingRepository.get_prices([X200_id])
    DB-->>Quote: unit_price=$450
    Quote->>Quote: QuoteBuilder.build() → total=$4500
    Quote->>DB: QuoteRepository.create(quote)
    Quote->>LLM: QuoteExplainer.explain(quote_result)
    LLM-->>Quote: narration string
    Quote-->>Executor: ToolExecutionResult(quote_id, total=$4500)

    Executor->>CRM: create_lead(session, context)
    CRM->>DB: LeadRepository.create(lead)
    CRM->>DB: RetryQueueRepository.enqueue(lead_id)
    Note over CRM: asyncio.create_task(send_lead_notification)
    CRM-->>Executor: ToolExecutionResult(lead_id)

    Executor->>LLM: respond — assemble final message
    LLM-->>Executor: "Here's your quote for 10 X200 switches: $4,500 total..."

    Orch->>DB: TurnsService.record_turn(all results)
    Orch-->>API: OrchestratorResult(assistant_message, intent, plan)
    API-->>Widget: ChatResponse {message, session_id}
    Widget-->>User: "Here's your quote for 10 X200 switches: $4,500 total..."
```

---

## 13. CRM Retry Worker Flow (M14 — Background)

```mermaid
flowchart TD
    SCHED(["APScheduler\nevery 60 seconds"])

    subgraph WORKER["RetryWorker.run_once()"]
        W_LOCK["SELECT * FROM retry_queue\nWHERE status='pending'\nAND next_retry_at <= now()\nFOR UPDATE SKIP LOCKED\nLIMIT 1"]
        W_CHECK{"Row found?"}
        W_IDLE["Sleep until\nnext schedule"]
        W_CRM["CRMService.create_lead(lead)\n(LocalCRMService → PostgreSQL\nOR real CRM HTTP client)"]
        W_OK{"CRM call\nsucceeded?"}
        W_MARK_OK["RetryQueueRepository\n.mark_synced()\n.mark_succeeded()"]
        W_BACKOFF{"attempts >=\nmax_retries (5)?"}
        W_PERM_FAIL["mark_permanently_failed()\nLog ERROR — manual review needed"]
        W_RETRY["Calculate exponential backoff\n2^attempts minutes\nUpdate next_retry_at"]
    end

    SCHED --> W_LOCK
    W_LOCK --> W_CHECK
    W_CHECK -->|"No"| W_IDLE
    W_CHECK -->|"Yes"| W_CRM
    W_CRM --> W_OK
    W_OK -->|"Yes"| W_MARK_OK
    W_OK -->|"No"| W_BACKOFF
    W_BACKOFF -->|"Yes"| W_PERM_FAIL
    W_BACKOFF -->|"No"| W_RETRY
```

---

## 14. Observability Flow (M16)

```mermaid
flowchart LR
    subgraph MODULES["All Modules emit metrics"]
        M6_M["M06: intent_classification_total\nintent_confidence_histogram"]
        M11_M["M11: rag_hit_total"]
        M12_M["M12: quote_generated_total\nquote_pdf_generated_total"]
        M14_M["M14: lead_created_total\ncrm_sync_total"]
        M18_M["M18: comparison_requests_total\ncompatibility_checks_total"]
        M19_M["M19: solution_builds_total\nwizard_sessions_total"]
        M20_M["M20: handoff_requests_total"]
        M21_M["M21: language_detection_total\ntranslation_requests_total"]
        M22_M["M22: availability_checks_total"]
    end

    subgraph REGISTRY["M16 — MetricsRegistry\n(prometheus_client, in-process)"]
        REG["Prometheus Counters\n+ Histograms"]
    end

    subgraph ENDPOINTS["M15 — Endpoints"]
        EP_METRICS["GET /metrics\n→ prometheus text format"]
        EP_READY["GET /ready\n→ { db, redis, ollama } status"]
    end

    MODULES --> REGISTRY
    REGISTRY --> EP_METRICS
    EP_READY --> DB_CHECK["Async DB ping"]
    EP_READY --> REDIS_CHECK["Redis ping"]
    EP_READY --> OLLAMA_CHECK["Ollama /api/tags check"]
```

---

## 15. Module Dependency Map

```mermaid
graph TD
    M01["M01\nFoundation\n& Config"]
    M02["M02\nDB & Cache\nLayer"]
    M03["M03\nSession &\nState"]
    M04["M04\nTurns &\nLogging"]
    M05["M05\nLLM Engine\n(Ollama)"]
    M06["M06\nRouter &\nOrchestrator"]
    M07["M07\nTask\nPlanner"]
    M08["M08\nPrompt\nManager"]
    M09["M09\nFeature\nFlags"]
    M10["M10\nSecurity &\nTool Executor"]
    M11["M11\nRAG Engine"]
    M12["M12\nQuote\nBuilder"]
    M13["M13\nClarification\nTemplates"]
    M14["M14\nCRM &\nEmail"]
    M15["M15\nPublic API"]
    M16["M16\nObservability"]
    M17["M17\nFrontend"]
    M18["M18\nProduct\nIntelligence"]
    M19["M19\nSolution\nBuilder"]
    M20["M20\nHandoff"]
    M21["M21\nMulti-language"]
    M22["M22\nAvailability"]
    SHARED["shared/\nintent_context.py"]

    M01 --> M02 --> M03 & M04 & M09 & M11 & M12 & M14 & M18 & M19 & M20 & M22
    M03 --> M06 & M19 & M21
    M04 --> M06 & M20
    M05 --> M06 & M12 & M18 & M19 & M21
    M06 --> M07 & M13 & M15
    M07 --> M10
    M08 --> M06
    M09 --> M06 & M07 & M10 & M11 & M18 & M19 & M20 & M21 & M22
    M10 --> M11 & M12 & M13 & M14 & M18 & M19 & M20 & M22
    M11 --> M18 & M19
    M12 --> M14
    M14 --> M20
    M16 --> M06 & M11 & M12 & M18 & M19 & M20 & M21 & M22
    SHARED --> M06 & M07
    M15 --> M17
```
