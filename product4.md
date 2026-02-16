# Product 4 Spec: NTUPOOL Chatbot (RAG)

Version: v2.1
Date: 2026-02-16
Stack: Flask + LangGraph + LangChain + Supabase pgvector + OpenAI-compatible API

## 1. Goal
Deliver a production-usable chatbot on `ntupool.org` that answers from website content using RAG, with source traceability and safe fallback behavior.

## 2. Delivered Scope (Implemented)

### 2.1 Backend
- `init_supabase.sql`
- `ingest.py`
- `app/services/chatbot/__init__.py`
- `app/services/chatbot/graph.py`
- `app/blueprints/chatbot.py`
- `app/__init__.py` (register chatbot blueprint)
- `app/config.py` (chatbot env config)
- `tests/test_chatbot_api.py`

### 2.2 Frontend Integration
- `app/templates/index.html` now includes chatbot panel.
- `app/static/js/chatbot.js` handles API call + CSRF header + reply rendering.

### 2.3 Deployment and Docs
- `deploy_update.bat` and `deploy.ps1` include chatbot env checks/injection.
- `requirements.txt` and `.env.example` include chatbot dependencies/config.
- `CHATBOT_DEPLOY.md` updated as deployment runbook.

## 3. Environment Variables

### 3.1 Required
- `DATABASE_URL`
- `OPENAI_API_KEY`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`

### 3.2 Optional (with code defaults)
- `OPENAI_BASE_URL` (for OpenRouter, use `https://openrouter.ai/api/v1`)
- `OPENAI_CHAT_MODEL` (default `gpt-4o-mini`)
- `OPENAI_EMBED_MODEL` (default `text-embedding-3-small`)
- `SUPABASE_DOCS_TABLE` (default `pool_documents`)
- `SUPABASE_MATCH_FUNCTION` (default `match_documents`)
- `CHATBOT_TOP_K` (default `3`)
- `CHATBOT_MIN_SCORE` (default `0.65`)
- `CHATBOT_MAX_CONTEXT_CHARS` (default `4000`)

Operational recommendation:
- For very small ingested datasets, set `CHATBOT_MIN_SCORE=0` to avoid over-filtering.

## 4. Database Contract (`init_supabase.sql`)
- Enables `vector` and `pgcrypto`.
- Table `public.pool_documents` includes:
  - `id uuid`
  - `content text`
  - `metadata jsonb`
  - `embedding vector(1536)`
  - `created_at timestamptz`
- Function `public.match_documents(query_embedding, match_count, filter)` returns:
  - `id`, `content`, `metadata`, `similarity`

## 5. Ingestion Contract (`ingest.py`)
- Requires `OPENAI_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`.
- Accepts:
  - `--url` (repeatable)
  - `--sitemap-url`
  - `--max-urls`
  - `--chunk-size`
  - `--chunk-overlap`
  - `--top-k`
  - `--debug-query`
- Domain guard: only `ntupool.org` allowed.
- Sitemap load failure falls back to homepage.
- Splitter import compatibility:
  - first `langchain_text_splitters`
  - fallback `langchain.text_splitter`

## 6. Graph and Retrieval Contract (`graph.py`)

### 6.1 State
- `question: str`
- `context: list[str]`
- `answer: str`
- `sources: list[str]`

### 6.2 Flow
- `retrieve_node`: retrieve docs from Supabase vector store.
- `generate_node`: answer with system prompt and truncated context.
- Graph edges: `START -> retrieve_node -> generate_node -> END`.

### 6.3 Compatibility Fallback
If `SupabaseVectorStore` methods fail due SDK version mismatch, fallback to direct RPC call to `match_documents`.

## 7. API Contract (`/api/chat`)
- Method: `POST`
- Request: `{"message":"..."}`
- Validation:
  - JSON object required
  - `message` string required
  - non-empty
  - max 2000 chars
- Responses:
  - `200`: `{"reply":"...","sources":[...]}`
  - `400`: bad input
  - `503`: chatbot not configured
  - `500`: internal error
- CSRF:
  - request must include valid `X-CSRFToken` in browser flow.

## 8. Frontend Contract
- Homepage includes chatbot UI card.
- `chatbot.js` fetches `/api/chat`, displays reply and sources, supports `Ctrl/Cmd + Enter` submit.

## 9. Testing and Acceptance

### 9.1 Automated
- `tests/test_chatbot_api.py` covers `200/400/500/503`.

### 9.2 Manual
- Homepage chatbot can submit question and render reply.
- Source links are displayed when retrieval includes source metadata.
- Unknown/low-confidence case returns polite fallback instead of hallucination.

## 10. Out of Scope
- Advanced crawler beyond provided URLs/sitemap.
- Multi-turn memory and conversation storage.
- Multi-language intent routing.
