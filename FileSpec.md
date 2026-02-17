# NTU Pool Web FileSpec

Last Updated: 2026-02-17

## 1. Scope
This document reflects the current codebase structure and runtime behavior for the NTU Pool Flask app, including the intent-routed chatbot integration.

## 2. Key File Map

```text
Swim_Pool_Web_Dev/
├─ app/
│  ├─ __init__.py
│  ├─ config.py
│  ├─ extensions.py
│  ├─ blueprints/
│  │  ├─ auth.py
│  │  ├─ social.py
│  │  ├─ weather.py
│  │  ├─ live_status.py
│  │  ├─ misc.py
│  │  └─ chatbot.py
│  ├─ services/
│  │  ├─ weather_engine.py
│  │  └─ chatbot/
│  │     ├─ __init__.py
│  │     └─ graph.py
│  ├─ static/js/
│  │  ├─ weather.js
│  │  ├─ weather_v2.js
│  │  ├─ live_status.js
│  │  └─ chatbot.js
│  └─ templates/
│     ├─ base.html
│     └─ index.html
├─ ingest.py
├─ sync_knowledge_base.py
├─ sync_knowledge_base.bat
├─ knowledge_base/
│  └─ README.md
├─ init_supabase.sql
├─ tests/test_chatbot_api.py
├─ tests/test_chatbot_graph.py
├─ deploy_update.bat
├─ deploy.ps1
├─ CHATBOT_DEPLOY.md
├─ product4.md
└─ FileSpec.md
```

## 3. Runtime Architecture

### 3.1 Flask App Initialization
- `app/__init__.py`
- Uses app factory `create_app()`.
- Registers all blueprints, including `chatbot_bp`.
- Enforces CSRF for state-changing methods (`POST/PUT/PATCH/DELETE`) via signed token.
- Production startup fails fast if `SECRET_KEY` is weak or DB URI is missing.

### 3.2 Configuration
- `app/config.py`
- Loads `.env` and exposes chatbot settings:
  - `OPENAI_API_KEY`
  - `OPENAI_BASE_URL`
  - `OPENAI_CHAT_MODEL` (default `gpt-4o-mini`)
  - `OPENAI_EMBED_MODEL` (default `text-embedding-3-small`)
  - `CHATBOT_INTENT_API_KEY` (fallback to `OPENROUTER_API_KEY`, then `OPENAI_API_KEY`)
  - `CHATBOT_INTENT_BASE_URL` (default `https://openrouter.ai/api/v1`)
  - `CHATBOT_INTENT_MODEL` (default `liquid/lfm-2.5-1.2b-thinking:free`)
  - `SUPABASE_URL`
  - `SUPABASE_SERVICE_ROLE_KEY`
  - `SUPABASE_DOCS_TABLE` (default `pool_documents`)
  - `SUPABASE_MATCH_FUNCTION` (default `match_documents`)
  - `SUPABASE_CHAT_LOG_TABLE` (default `chatbot_conversations`)
  - `CHATBOT_TOP_K` (default `3`)
  - `CHATBOT_MIN_SCORE` (default `0.45`)
  - `CHATBOT_MAX_CONTEXT_CHARS` (default `4000`)
  - `CHATBOT_DB_TOOL_MAX_CALLS` (default `4`)

## 4. Chatbot Backend

### 4.1 API Layer
- `app/blueprints/chatbot.py`
- Routes:
  - `POST /api/chat`
  - `POST /api/chat/feedback`
- `/api/chat` request JSON: `{"message": "..."}`
- `/api/chat` validation:
  - user must be authenticated
  - body must be JSON object
  - `message` must be non-empty string
  - max length: 2000
- `/api/chat` response:
  - `200`: `{"reply":"...","sources":[...],"conversation_id":"...","message_counter":N,"feedback_required":bool,"feedback_prompt":"..."?}`
  - `400`: invalid input
  - `401`: login required
  - `503`: chatbot configuration/dependency unavailable
  - `500`: internal runtime/logging error
- `/api/chat/feedback` request JSON: `{"conversation_id":"<uuid>","rating":1..5}`
- `/api/chat/feedback` validation:
  - user must be authenticated
  - `conversation_id` must be valid UUID string
  - `rating` must be integer between 1 and 5
- `/api/chat/feedback` response:
  - `200`: `{"ok":true,"conversation_id":"...","rating":N}`
  - `400`: invalid payload or invalid rating state
  - `401`: login required
  - `503`: configuration/dependency unavailable
  - `500`: internal persistence error

### 4.2 Chat Persistence and Feedback
- Every successful `/api/chat` reply is persisted to Supabase table `chatbot_conversations`.
- Stored fields include:
  - identity/time: `id`, `created_at`, `user_id`
  - content: `user_message`, `assistant_message`, `sources`
  - counters/feedback: `message_counter`, `feedback_requested`, `rating_score`, `rating_submitted_at`
  - request metadata: `request_ip`, `user_agent`
- `message_counter` is per-user cumulative count.
- `feedback_requested` is set true on each 10th user message (`10/20/30...`).
- `/api/chat/feedback` updates rating only when:
  - row belongs to current user
  - `feedback_requested=true`
  - `rating_score` is still null

### 4.3 Graph Layer
- `app/services/chatbot/graph.py`
- Builds chatbot graph: `START -> intent_node -> retrieve_node -> generate_node -> END`
- Key behaviors:
  - lazy initialization + cache (`get_rag_app()`)
  - intent-first routing (dedicated intent model):
    - `small_talk`: direct LLM chat
    - `database`: function calling to DB tools (posts/comments/reports/stats), then LLM summary
    - `knowledge_base`: vector retrieval via `SupabaseVectorStore` + RAG answer
    - `fallback`: out-of-scope fallback reply
  - backend-rules-aware retrieval for knowledge queries:
    - detects backend rules/config questions (for example lightning/rain thresholds, persistence windows, consensus logic, runtime settings)
    - prioritizes backend context docs (`backend_runtime_live`, `backend_non_sensitive`, `realtime_status_snapshot`) before generic vector similarity retrieval
  - score filtering when score is available, with top-k fallback if all candidates are filtered out
  - context truncation by `CHATBOT_MAX_CONTEXT_CHARS`
  - language-aware behavior:
    - answer language follows user language
    - unknown fallback text is Chinese/English based on question language

### 4.4 Supabase SDK Compatibility Fallback
`_search_with_optional_scores()` now has a fallback path:
- Tries `similarity_search_with_relevance_scores`
- Tries `similarity_search_with_score`
- Tries `similarity_search`
- If vector-store methods fail due SDK incompatibility, directly calls RPC:
  - `client.rpc(query_name, {query_embedding, match_count, filter})`

This keeps `/api/chat` usable across newer `supabase` + `langchain-community` combinations.

## 5. Ingestion Pipeline

### 5.1 Database Objects
- `init_supabase.sql`
- Creates:
  - extension `vector`
  - extension `pgcrypto`
  - table `public.pool_documents` (`embedding vector(1536)`)
  - table `public.chatbot_conversations` (chat logs + feedback)
  - function `public.match_documents(...)`

### 5.2 Ingestion Script
- `sync_knowledge_base.py` (primary)
- `ingest.py` (legacy website-only ingest)
- Loads env via `python-dotenv`.
- Requires:
  - `OPENAI_API_KEY`
  - `SUPABASE_URL`
  - `SUPABASE_SERVICE_ROLE_KEY`
- Primary sync sources:
  - `ntupool.org` sitemap pages
  - runtime pool status snapshot
  - live manual report records
  - community posts/comments
  - backend non-sensitive config snapshot
  - local markdown files in `knowledge_base/`
- Sync strategy is incremental by default:
  - compares `doc_key` + `doc_hash` in metadata
  - inserts only new docs
  - replaces only changed docs
  - deletes removed docs
- Supports `--full-rebuild` to force namespace-level rebuild.
- If sitemap is unavailable, script falls back to auto-discovered public GET routes from Flask `url_map`.
- Splits docs with `RecursiveCharacterTextSplitter`.
- Adds metadata fields including `source` and `chunk`.
- Embeds with `OpenAIEmbeddings` and inserts into Supabase.
- Supports both imports for splitter:
  - `langchain_text_splitters`
  - fallback `langchain.text_splitter`

## 6. Frontend Chatbot Integration

### 6.1 UI Placement
- `app/templates/base.html`
- Adds floating `NTU Pool Assistant` launcher button and popup panel globally for all pages that extend base template, with:
  - guest mode: login prompt (no send textarea)
  - logged-in mode: question textarea + submit button
  - reply thread + source links panel
  - per-10-message assistant feedback block (5-star buttons)

### 6.2 Frontend Client
- `app/static/js/chatbot.js`
- Sends `POST /api/chat` with:
  - `Content-Type: application/json`
  - `X-CSRFToken` from `<meta name="csrf-token">`
- Supports click submit and `Enter` to send; `Ctrl/Cmd + Enter` inserts newline.
- Renders reply, sources, and feedback widget when `feedback_required=true`.
- Sends `POST /api/chat/feedback` with `conversation_id` and `rating`.

## 7. Deployment Behavior

### 7.1 Scripts
- `deploy_update.bat` (CMD)
- `deploy.ps1` (PowerShell)

### 7.2 Required Env For Deploy
Both scripts require:
- `DATABASE_URL`
- `OPENAI_API_KEY`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

`deploy_update.bat` behavior (double-click):
- auto-loads variables from project `.env` when present
- falls back to `SQLALCHEMY_DATABASE_URI` if `DATABASE_URL` is missing
- supports `--check-only` to validate required env without build/deploy

Optional env with defaults:
- `OPENAI_CHAT_MODEL`
- `OPENAI_EMBED_MODEL`
- `CHATBOT_INTENT_API_KEY`
- `CHATBOT_INTENT_BASE_URL`
- `CHATBOT_INTENT_MODEL`
- `SUPABASE_DOCS_TABLE`
- `SUPABASE_MATCH_FUNCTION`
- `SUPABASE_CHAT_LOG_TABLE`
- `CHATBOT_TOP_K`
- `CHATBOT_MIN_SCORE`
- `CHATBOT_MAX_CONTEXT_CHARS`
- `CHATBOT_DB_TOOL_MAX_CALLS`
- `OPENAI_BASE_URL`

If `SECRET_KEY` is missing, deploy script auto-generates one for that deployment.

## 8. Tests
- `tests/test_chatbot_api.py`
- `tests/test_chatbot_graph.py`
- Covers:
  - success `200`
  - input validation `400`
  - auth enforcement `401`
  - internal error `500`
  - config error `503`
  - feedback endpoint validation and success path
  - graph-level small-talk bypass behavior
  - intent guardrail behavior (fallback override by heuristics)
  - backend-rules-question detection and backend-priority retrieval path
  - language-aware unknown fallback behavior

## 9. Operational Note
For very small corpora (for example only homepage chunks), reduce `CHATBOT_MIN_SCORE` further (for example to `0.3` or `0`) if recall remains too strict.
