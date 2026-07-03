# Module 21 — Multi-language Support (EN / UR / AR)

## 1. Module Name
`language` — Automatic language detection, session language preference management, and response translation.

## 2. Goal
Enable the chatbot to respond in the user's detected or preferred language. All internal processing (retrieval, planning, tool execution, LLM business logic) runs in English. Translation occurs **only at response assembly** — the final `assistant_message` is translated before being returned in `OrchestratorResult`.

## 3. Purpose
Isolating language concerns prevents language logic from leaking into retrieval queries, planner rules, or tool results. The translation-at-the-boundary design means all ML models, search indices, and business rules remain English-only, which is consistent with how Qdrant vectors are embedded (from English product data) and how the intent classifier is prompted.

## 4. Dependencies
Module 01 (config — `settings.language`), Module 03 (ConversationState — stores `language_code`), Module 05 (LLM — `LLMClientProtocol` for translation), Module 06 (Orchestrator integration — detection runs at turn start), Module 09 (`FeatureFlags.enable_multi_language`).

## 5. Folder Structure
```
app/
├── language/
│   ├── __init__.py
│   ├── detection_service.py
│   ├── translation_service.py
│   └── schemas.py
tests/
└── unit/
    ├── test_detection_service.py
    └── test_translation_service.py
```

## 6. Files to Create
`detection_service.py`, `translation_service.py`, `schemas.py`.

## 7. Responsibility of Every File
| File | Responsibility |
|---|---|
| `detection_service.py` | `LanguageDetectionService.detect(text) -> LanguageCode` |
| `translation_service.py` | `TranslationService.translate(text, target) -> str` |
| `schemas.py` | `LanguageCode` type alias and validation |

## 8. Classes

### `LanguageDetectionService`
```python
class LanguageDetectionService:
    SUPPORTED: frozenset[str] = frozenset({'en', 'ur', 'ar'})

    def detect(self, text: str) -> str:
        """
        Uses langdetect library to detect language code.
        Maps detected code to one of SUPPORTED codes.
        Falls back to 'en' for unsupported or detection failure.
        Returns: 'en' | 'ur' | 'ar'
        """
```

Detection library: `langdetect` (PyPI, MIT license). Lightweight, no external API calls.

Detection mapping:
- `langdetect` returns `'ur'` → map to `'ur'`
- `langdetect` returns `'ar'` → map to `'ar'`
- `langdetect` returns `'en'` → map to `'en'`
- Anything else → `'en'`

Minimum text length for detection: 10 characters. If text is shorter, return session's existing `language_code` or `'en'`.

### `TranslationService`
```python
class TranslationService:
    async def translate(
        self,
        text: str,
        target: str,
        llm_client: LLMClientProtocol,
    ) -> str:
        """
        If target == 'en': return text unchanged (all internal text is already English).
        Otherwise: call LLMClientProtocol.chat with translation prompt.
        Translation prompt instructs LLM to translate the text to the target language
        while preserving formatting (bullet points, numbers, line breaks).
        """
```

Translation uses `qwen2.5:3b` via the existing `LLMClientProtocol` — no external translation API.

Translation prompt template (stored in `prompt_library/translation/translate_response_v1.md`):
```
You are a professional translator.
Translate the following text to {target_language_name}.
Preserve all formatting exactly: bullet points, numbers, line breaks, product names, and prices.
Do not add any commentary. Return only the translated text.

Text to translate:
{text}
```

### Language Code Mapping
```python
LANGUAGE_NAMES: dict[str, str] = {
    'en': 'English',
    'ur': 'Urdu',
    'ar': 'Arabic (Modern Standard)',
}
```

## 9. Data Models
No new database tables. Language preference is stored in `conversation_state.language_code TEXT DEFAULT 'en'`:
```sql
-- Migration: add language_code column to conversation_state table (Module 03's table)
ALTER TABLE conversation_state ADD COLUMN language_code TEXT NOT NULL DEFAULT 'en';
```

## 10. Pydantic Schemas
```python
from typing import Literal
LanguageCode = Literal['en', 'ur', 'ar']

class LanguagePreference(BaseModel):
    code: LanguageCode = 'en'
    detected_this_turn: bool = False
```

## 11. Repository Layer
None new. Language code is stored via `SessionStateService.update_conversation_state` (Module 03). No separate repository for this module.

## 12. Service Layer — Orchestrator Integration

Language detection and translation are integrated into `Orchestrator.on_turn` (Module 06). These are **not** tool steps — they run outside the Planner/Executor pipeline.

**Step added before facts extraction (Step 2a in Module 06 §12 Service Layer):**
```python
# After loading facts and state, before FactsExtractor runs
if flags.enable_multi_language:
    detected_lang = LanguageDetectionService().detect(user_message)
    if detected_lang != state.language_code:
        state = await SessionStateService.update_conversation_state(
            tenant_id, session_id, {'language_code': detected_lang}
        )
```

**Step added at response assembly (Step 13a in Module 06 §12, after assembling `assistant_message`):**
```python
if flags.enable_multi_language and state.language_code != 'en':
    assistant_message = await TranslationService().translate(
        text=assistant_message,
        target=state.language_code,
        llm_client=llm_client,
    )
```

This integration adds at most 1 LLM call per turn (translation) and 1 detection call (no LLM, pure library). Both are skipped when `enable_multi_language=False` (the default).

## 13. Internal Interfaces
- `LanguageDetectionService.detect(text: str) -> str` — synchronous, no I/O.
- `TranslationService.translate(text, target, llm_client) -> str` — async, 1 LLM call.
- Neither service is exposed as a Tool Executor step — both are called directly by the Orchestrator.

## 14. Database Tables
No new tables. `conversation_state.language_code` column added via migration (see §9).

## 15. Redis Keys
None new. Language code is cached as part of the session state in Redis key `conversation:state:{tenant_id}:{session_id}` (owned by Module 03).

## 16. API Endpoints
`POST /chat/language` (owned by Module 15) — allows the frontend widget to explicitly set language preference:
```json
POST /chat/language
{
  "session_id": "...",
  "language_code": "ur"
}
```
Response: `{ "language_code": "ur", "status": "set" }`.
This endpoint calls `SessionStateService.update_conversation_state(tenant_id, session_id, {'language_code': 'ur'})` directly — no Orchestrator involvement.

## 17. Request Models
`LanguageSetRequest { session_id: str, language_code: LanguageCode }`.

## 18. Response Models
`LanguageSetResponse { language_code: LanguageCode, status: str }`.

## 19. Business Logic
- **Internal-English principle**: All tool results, RAG chunks, plan steps, and facts remain in English at all times. The translation boundary is strictly at `OrchestratorResult.assistant_message` construction.
- **Detection on every turn**: Language can shift mid-conversation (user may switch languages). Detection runs every turn when `enable_multi_language=True`.
- **Explicit override wins**: If the frontend has called `POST /chat/language`, the stored `language_code` is used regardless of auto-detection result.
- **Urdu script**: Urdu responses use Nastaliq (Arabic script) as standard; no special rendering required — the frontend widget already handles RTL via CSS (see Module 17).

## 20. Validation Rules
- `language_code` must be one of `{'en', 'ur', 'ar'}`. Any other value rejected with `422 Unprocessable Entity` at the API layer (Module 15).
- If `langdetect` raises any exception (short text, mixed script), detection silently falls back to current `state.language_code`.

## 21. Error Handling
| Error | Handling |
|---|---|
| `langdetect.LangDetectException` | Fall back to current `state.language_code`, log at `DEBUG` |
| LLM translation failure | Return original English text, log at `WARNING` — never block the turn |
| Unsupported language detected | Map to `'en'`, log at `DEBUG` |

## 22. Logging Strategy
- Log language detection result at `DEBUG` per turn (not `INFO` to avoid log volume).
- Log successful translation at `DEBUG`: `from=en`, `to={lang}`, `character_count`.
- Log translation failure at `WARNING`.

## 23. Unit Tests
- `test_detect_returns_en_for_english_text`
- `test_detect_returns_ur_for_urdu_text`
- `test_detect_returns_ar_for_arabic_text`
- `test_detect_falls_back_to_en_on_short_text`
- `test_translate_skips_when_target_is_en`
- `test_translate_calls_llm_for_non_english_target`
- `test_translate_falls_back_to_original_on_llm_failure`

## 24. Integration Tests
- `test_language_detection_updates_conversation_state`
- `test_orchestrator_translates_response_to_urdu`
- `test_explicit_language_override_takes_precedence`

## 25. Configuration
```python
class LanguageSettings(BaseModel):
    default_language: str = 'en'
    supported_languages: list[str] = ['en', 'ur', 'ar']
    translation_prompt_template: str = 'translation/translate_response_v1.md'
```
Added to `Settings` in Module 01.

## 26. Environment Variables
`ENABLE_MULTI_LANGUAGE=false` (default, opt-in per Module 09).

## 27. Sequence Diagram
```
Orchestrator.on_turn(tenant_id, session_id, user_message)
    │
    ├─ [if enable_multi_language]
    │     detected_lang = LanguageDetectionService.detect(user_message)
    │     update conversation_state.language_code if changed
    │
    ├─ [normal turn pipeline: facts, classification, planning, execution]
    │
    ├─ assistant_message = assemble_response(tool_results)
    │
    └─ [if enable_multi_language and language_code != 'en']
          assistant_message = await TranslationService.translate(assistant_message, language_code)
    │
    └─ return OrchestratorResult(assistant_message=...)
```

## 28. Request Lifecycle
Detection is in-process at turn start. Translation is in-process at turn end. Both add negligible latency when `enable_multi_language=False` (short-circuit skip).

## 29. Data Flow
`user_message` → `LanguageDetectionService` → `conversation_state.language_code` → (full turn) → `assistant_message` → `TranslationService` → translated `assistant_message` → HTTP response.

## 30. Example Workflow
1. User sends message in Urdu: "مجھے نیٹ ورکنگ سوئچ چاہیے"
2. `LanguageDetectionService.detect()` → `'ur'`
3. `conversation_state.language_code` updated to `'ur'`
4. Intent classified (Tier 2 handles mixed-language prompts)
5. RAG retrieval runs in English using extracted filter terms
6. Response assembled in English: "Here are the top switches for your needs: ..."
7. `TranslationService.translate(response, 'ur')` → Urdu translation
8. `OrchestratorResult.assistant_message` = translated Urdu text

## 31. Future Extension Points
- Additional languages: French, Chinese (Simplified), Hindi — add to `SUPPORTED` and `LANGUAGE_NAMES`.
- Dedicated translation model instead of Qwen (e.g., Helsinki-NLP OPUS-MT) for lower latency.
- Frontend RTL layout improvements for Arabic (full bidirectional support).

## 32. Completion Checklist
- [ ] `langdetect` installed in `requirements.txt`
- [ ] `conversation_state.language_code` migration applied
- [ ] Orchestrator integration adds detection at turn start and translation at turn end
- [ ] `POST /chat/language` endpoint registered in Module 15
- [ ] Translation falls back gracefully on LLM failure
- [ ] Tests above pass
