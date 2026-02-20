# Product 4 Spec: NTUPOOL Chatbot (Intent-Routed RAG)

Version: v2.5
Date: 2026-02-20
Stack: Flask + LangGraph + LangChain + Supabase pgvector + OpenAI-compatible API

## 1. Goal
Deliver a production-usable chatbot on `ntupool.org` that:
- answers pool/community factual queries from website/app content using intent-routed RAG
- supports direct small-talk chat via LLM without vector retrieval
- enforces authenticated chat usage (guest sees login prompt)
- records chat history and star feedback in Supabase
- preserves source traceability and safe language-aware fallback behavior

## 2. Delivered Scope (Implemented)

### 2.1 Backend
- `init_supabase.sql`
- `sync_knowledge_base.py`
- `ingest.py` (legacy)
- `app/services/chatbot/__init__.py`
- `app/services/chatbot/graph.py`
- `app/blueprints/chatbot.py`
- `app/__init__.py` (register chatbot blueprint)
- `app/config.py` (chatbot env config)
- `tests/test_chatbot_api.py`
- `tests/test_chatbot_graph.py`

### 2.2 Frontend Integration
- `app/templates/base.html` includes floating chatbot panel with auth-aware composer:
  - guest: login prompt block (no send input)
  - logged in: message textarea + send button
- `app/static/js/chatbot.js` handles:
  - `/api/chat/stream` + CSRF auto-refresh/retry
  - thread rendering + sources
  - 5-star feedback widget rendering and submit (`/api/chat/feedback`) with CSRF auto-refresh/retry

### 2.3 Deployment and Docs
- `deploy_update.bat` includes chatbot env checks/injection.
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
- `CHATBOT_INTENT_API_KEY` (fallback: `OPENROUTER_API_KEY`, then `OPENAI_API_KEY`)
- `CHATBOT_INTENT_BASE_URL` (default `https://openrouter.ai/api/v1`)
- `CHATBOT_INTENT_MODEL` (default `liquid/lfm-2.5-1.2b-thinking:free`)
- `SUPABASE_DOCS_TABLE` (default `pool_documents`)
- `SUPABASE_MATCH_FUNCTION` (default `match_documents`)
- `SUPABASE_CHAT_LOG_TABLE` (default `chatbot_conversations`)
- `CHATBOT_TOP_K` (default `3`)
- `CHATBOT_MIN_SCORE` (default `0.45`)
- `CHATBOT_MAX_CONTEXT_CHARS` (default `4000`)
- `CHATBOT_DB_TOOL_MAX_CALLS` (default `4`)

Operational recommendation:
- Start from `CHATBOT_MIN_SCORE=0.45`; lower to `0.3` or `0` only if recall is still too strict.

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
- Table `public.chatbot_conversations` includes:
  - `id uuid`, `created_at timestamptz`, `user_id bigint`
  - `user_message text`, `assistant_message text`, `sources jsonb`
  - `message_counter bigint` (per-user cumulative)
  - `feedback_requested boolean`
  - `rating_score smallint (1-5)`, `rating_submitted_at timestamptz`
  - `request_ip text`, `user_agent text`
  - unique constraint on `(user_id, message_counter)`

## 5. Ingestion Contract (`sync_knowledge_base.py`)
- Requires `OPENAI_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`.
- Accepts:
  - `--sitemap-url`
  - `--max-urls`
  - `--chunk-size`
  - `--chunk-overlap`
  - `--top-k`
  - `--full-rebuild`
  - `--debug-query`
- Domain guard: only `ntupool.org` allowed.
- Incremental sync by default (new/changed/deleted docs only).
- Sitemap load failure falls back to discovered app routes.
- Splitter import compatibility:
  - first `langchain_text_splitters`
  - fallback `langchain.text_splitter`

## 6. Graph and Retrieval Contract (`graph.py`)

### 6.1 State
- `question: str`
- `intent: str` (`small_talk|database|knowledge_base|fallback`)
- `mode: str` (execution mode derived from intent)
- `context: list[str]`
- `answer: str`
- `sources: list[str]`

### 6.2 Flow
- `intent_node`:
  - classify user message via intent model (`CHATBOT_INTENT_MODEL`)
  - normalize model output and apply heuristic guardrail when needed
- `retrieve_node`:
  - `small_talk`: skip retrieval
  - `database`: execute DB tool-use/function-calling pipeline
  - `knowledge_base`: retrieve docs from Supabase vector store
  - `fallback`: skip retrieval and return out-of-scope fallback
- `generate_node`:
  - `small_talk`: direct LLM reply, no vector retrieval, `sources=[]`
  - `database`: summarize tool results in user language
  - `knowledge_base`: answer with RAG prompt and truncated context
  - `fallback`: return scope fallback reply
  - response language follows user language
  - unknown fallback message is language-aware (Chinese/English)
- Graph edges: `START -> intent_node -> retrieve_node -> generate_node -> END`.

### 6.3 Backend-Rules Priority Retrieval
- For backend rules/config questions (for example lightning/rain thresholds, persistence windows, consensus logic, runtime settings), retrieval prioritizes backend context docs (`backend_runtime_live`, `backend_non_sensitive`, `realtime_status_snapshot`) before generic similarity search.

### 6.4 Compatibility Fallback
If `SupabaseVectorStore` methods fail due SDK version mismatch, fallback to direct RPC call to `match_documents`.

## 7. API Contract

### 7.1 `POST /api/chat`
- Request: `{"message":"..."}`
- Validation:
  - authenticated user required
  - JSON object required
  - `message` string required
  - non-empty
  - max 2000 chars
- Responses:
  - `200`: `{"reply":"...","sources":[...],"conversation_id":"...","message_counter":N,"feedback_required":bool,"feedback_prompt":"..."?}`
  - `400`: bad input
  - `401`: login required
  - `503`: chatbot not configured
  - `500`: internal error (including persistence error)
- Behavior:
  - writes one row to `chatbot_conversations`
  - sets `feedback_required=true` on each 5th cumulative message per user

### 7.2 `POST /api/chat/feedback`
- Request: `{"conversation_id":"<uuid>","rating":1..5}`
- Validation:
  - authenticated user required
  - valid UUID `conversation_id`
  - integer `rating` in range `1..5`
  - conversation row must belong to current user
  - row must have `feedback_requested=true`
  - row must not have existing `rating_score`
- Responses:
  - `200`: `{"ok":true,"conversation_id":"...","rating":N}`
  - `400`: invalid payload or invalid rating state
  - `401`: login required
  - `503`: chatbot not configured
  - `500`: internal error
- CSRF:
  - request must include valid `X-CSRFToken` in browser flow.
  - stale token recovery uses `GET /api/csrf-token`, then frontend retries once.

### 7.3 `GET /api/csrf-token`
- Purpose:
  - provide a fresh CSRF token for browser clients without full page reload
- Response:
  - `200`: `{"csrf_token":"<signed-token>"}` with `Cache-Control: no-store`

## 8. Frontend Contract
- Homepage includes floating chatbot launcher + popup panel.
- Guest panel shows login prompt only.
- Logged-in panel supports input submit (`Enter` to send, `Ctrl/Cmd + Enter` newline).
- Chat send and feedback submit automatically refresh CSRF token and retry once on CSRF `400`.
- Reply message renders sources when provided.
- On `feedback_required=true`, frontend appends a 5-star rating widget to assistant bubble.
- Rating click posts to `/api/chat/feedback` and locks after success.

## 9. Testing and Acceptance

### 9.1 Automated
- `tests/test_chatbot_api.py` covers `200/400/401/500/503` and feedback endpoint.
- `tests/test_chatbot_graph.py` covers:
  - intent classification and guardrail behavior
  - backend-rules detection and backend-priority retrieval path
  - database tool-use path
  - score fallback and vector search compatibility fallback
  - language-aware unknown reply and small-talk retrieval bypass

### 9.2 Manual
- Guest sees login prompt in chatbot panel and cannot send chat.
- Logged-in user can submit question and render reply.
- Source links are displayed when retrieval includes source metadata.
- Unknown/low-confidence case returns polite fallback instead of hallucination.
- `hi`/`hello`/`���` should return direct chat response without source links.
- Chinese input should receive Chinese reply; English input should receive English reply.
- At message count 5/10/15..., 5-star feedback UI appears and rating can be saved once.

## 10. Out of Scope
- Advanced crawler beyond provided URLs/sitemap.
- Cross-session multi-turn memory for answer generation.
- Fine-tuned domain intent model training (current implementation uses external model + local heuristics).

