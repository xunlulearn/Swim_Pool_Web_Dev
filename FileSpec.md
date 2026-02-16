# NTU Pool Web FileSpec

Last Updated: 2026-02-16

## 1. Scope
This document reflects the current codebase structure and runtime behavior for the NTU Pool Flask app, including the RAG chatbot integration.

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
├─ init_supabase.sql
├─ tests/test_chatbot_api.py
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
  - `SUPABASE_URL`
  - `SUPABASE_SERVICE_ROLE_KEY`
  - `SUPABASE_DOCS_TABLE` (default `pool_documents`)
  - `SUPABASE_MATCH_FUNCTION` (default `match_documents`)
  - `CHATBOT_TOP_K` (default `3`)
  - `CHATBOT_MIN_SCORE` (default `0.65`)
  - `CHATBOT_MAX_CONTEXT_CHARS` (default `4000`)

## 4. Chatbot Backend

### 4.1 API Layer
- `app/blueprints/chatbot.py`
- Route: `POST /api/chat`
- Request JSON: `{"message": "..."}`
- Validation:
  - body must be JSON object
  - `message` must be non-empty string
  - max length: 2000
- Responses:
  - `200`: `{"reply": "...", "sources": [...]}`
  - `400`: invalid input
  - `503`: chatbot configuration/dependency unavailable
  - `500`: internal runtime error

### 4.2 Graph Layer
- `app/services/chatbot/graph.py`
- Builds RAG graph: `START -> retrieve_node -> generate_node -> END`
- Key behaviors:
  - lazy initialization + cache (`get_rag_app()`)
  - retrieval via `SupabaseVectorStore`
  - score filtering when score is available
  - context truncation by `CHATBOT_MAX_CONTEXT_CHARS`
  - Chinese fallback reply when context is empty

### 4.3 Supabase SDK Compatibility Fallback
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
  - function `public.match_documents(...)`

### 5.2 Ingestion Script
- `ingest.py`
- Loads env via `python-dotenv`.
- Requires:
  - `OPENAI_API_KEY`
  - `SUPABASE_URL`
  - `SUPABASE_SERVICE_ROLE_KEY`
- Defaults to sitemap URL (`https://ntupool.org/sitemap.xml`), then falls back to homepage on failure.
- Restricts crawl domain to `ntupool.org`.
- Splits docs with `RecursiveCharacterTextSplitter`.
- Adds metadata fields including `source` and `chunk`.
- Embeds with `OpenAIEmbeddings` and inserts into Supabase.
- Supports both imports for splitter:
  - `langchain_text_splitters`
  - fallback `langchain.text_splitter`

## 6. Frontend Chatbot Integration

### 6.1 UI Placement
- `app/templates/index.html`
- Adds `NTU Pool Assistant` card with:
  - question textarea
  - submit button
  - reply panel
  - source links panel

### 6.2 Frontend Client
- `app/static/js/chatbot.js`
- Sends `POST /api/chat` with:
  - `Content-Type: application/json`
  - `X-CSRFToken` from `<meta name="csrf-token">`
- Supports click submit and `Ctrl/Cmd + Enter`.
- Renders reply and sources.

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

Optional env with defaults:
- `OPENAI_CHAT_MODEL`
- `OPENAI_EMBED_MODEL`
- `SUPABASE_DOCS_TABLE`
- `SUPABASE_MATCH_FUNCTION`
- `CHATBOT_TOP_K`
- `CHATBOT_MIN_SCORE`
- `CHATBOT_MAX_CONTEXT_CHARS`
- `OPENAI_BASE_URL`

If `SECRET_KEY` is missing, deploy script auto-generates one for that deployment.

## 8. Tests
- `tests/test_chatbot_api.py`
- Covers:
  - success `200`
  - input validation `400`
  - internal error `500`
  - config error `503`

## 9. Operational Note
For very small corpora (for example only homepage chunks), `CHATBOT_MIN_SCORE=0` is often needed to avoid over-filtering and returning fallback for every question.
