# Chatbot Deployment Guide

Updated: 2026-02-20

This runbook matches the current NTU Pool codebase and deployment scripts.

## 1. Required Environment Variables

Required:
1. `DATABASE_URL`
2. `OPENAI_API_KEY`
3. `SUPABASE_URL`
4. `SUPABASE_SERVICE_ROLE_KEY`

Optional (defaults in code):
1. `OPENAI_BASE_URL` (OpenRouter example: `https://openrouter.ai/api/v1`)
2. `OPENAI_CHAT_MODEL` (default `gpt-4o-mini`)
3. `OPENAI_EMBED_MODEL` (default `text-embedding-3-small`)
4. `CHATBOT_INTENT_API_KEY` (default fallback: `OPENROUTER_API_KEY`, then `OPENAI_API_KEY`)
5. `CHATBOT_INTENT_BASE_URL` (default `https://openrouter.ai/api/v1`)
6. `CHATBOT_INTENT_MODEL` (default `liquid/lfm-2.5-1.2b-thinking:free`)
7. `SUPABASE_DOCS_TABLE` (default `pool_documents`)
8. `SUPABASE_MATCH_FUNCTION` (default `match_documents`)
9. `SUPABASE_CHAT_LOG_TABLE` (default `chatbot_conversations`)
10. `CHATBOT_TOP_K` (default `3`)
11. `CHATBOT_MIN_SCORE` (default `0.45`)
12. `CHATBOT_MAX_CONTEXT_CHARS` (default `4000`)
13. `CHATBOT_DB_TOOL_MAX_CALLS` (default `4`)
14. `NEA_API_KEY` (weather module)
15. `SECRET_KEY` (if missing, deploy script auto-generates)
16. `SUPABASE_INTENT_LLM_FAILURE_TABLE` (default `chatbot_intent_model_failures`)
17. `SUPABASE_QA_LLM_FAILURE_TABLE` (default `chatbot_qa_model_failures`)

Practical recommendation:
- Start from `CHATBOT_MIN_SCORE=0.45`; lower to `0.3` or `0` only when recall is still too strict.

## 1.1 Chatbot Behavior Notes
1. `/api/chat` requires login. Unauthenticated requests return `401`.
2. `/api/chat` runtime now routes by **intent classification first** (dedicated model):
   - `small_talk`: direct LLM reply
   - `database`: tool-use/function-calling -> direct DB query -> LLM summary
   - `knowledge_base`: RAG retrieval + LLM generation
   - `fallback`: out-of-scope fallback reply
3. For backend rules/config questions (for example lightning/rain thresholds, persistence windows, consensus logic, runtime settings), knowledge path prioritizes backend snapshot context before generic vector similarity retrieval.
4. Replies follow the user's language (Chinese question -> Chinese reply, English question -> English reply).
5. For unknown answers, fallback text is language-aware (Chinese/English).
6. Every successful chat is persisted to Supabase (`chatbot_conversations`) with:
   - timestamp, user id, user/assistant messages
   - `message_counter`, `sources`, request metadata
   - feedback fields (`feedback_requested`, `rating_score`, `rating_submitted_at`)
7. Every 5th cumulative user message (5/10/15...) returns feedback metadata; frontend renders 5-star rating UI.
8. Rating submission uses `POST /api/chat/feedback` and stores a 1-5 score in Supabase.
9. Non-English input translation now uses intent model first and falls back to QA model when primary translation fails.
10. Every model invocation failure is logged in Supabase:
   - intent model failures -> `chatbot_intent_model_failures`
   - QA model failures -> `chatbot_qa_model_failures`
11. CSRF recovery for browser clients:
   - `GET /api/csrf-token` returns a fresh token (`Cache-Control: no-store`)
   - frontend chat/report flows refresh token and retry once when a CSRF `400` is returned

## 2. Supabase Initialization
1. Open Supabase SQL Editor.
2. Run `init_supabase.sql`.
3. Verify:
   - table `pool_documents`
   - table `chatbot_conversations`
   - table `chatbot_intent_model_failures`
   - table `chatbot_qa_model_failures`
   - function `match_documents`

## 3. Install Dependencies and Run Knowledge Sync (use `.venv` only)

Long-term maintenance policy: run all Python commands in this repository with `.venv`.
Recommended entrypoint on Windows: `dev.bat`.

### 3.1 Create and prepare `.venv`

CMD:
```bat
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

PowerShell:
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 3.2 Run knowledge sync in `.venv`

```bat
dev.bat sync
```

Recommended preflight checks:

```bat
dev.bat doctor --strict
dev.bat doctor --require-release-tools
dev.bat doctor --require-deploy-tools
```

Notes:
- `sync_knowledge_base.py` requires `OPENAI_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`.
- Default mode is incremental sync (doc hash based): only inserts new docs/chunks, updates changed docs, and removes deleted docs.
- Sources include website pages, runtime status snapshot, community posts/reports, backend non-sensitive info, and local Markdown files in `knowledge_base/`.
- Default sitemap is `https://ntupool.org/sitemap.xml`.
- If sitemap is unavailable, sync script auto-discovers public GET routes from Flask app and crawls those URLs as fallback.

Double-click workflow (Windows Explorer):

```bat
sync_knowledge_base.bat
```

Optional debug query preview:

```bat
dev.bat sync --debug-query "泳池什么时候开放"
```

Force full namespace rebuild when needed:

```bat
dev.bat sync --full-rebuild
```

## 4. Local Smoke Test

### 4.1 API smoke (requires valid CSRF token)
- Start app locally.
- Use browser flow or test client flow that includes `X-CSRFToken`.
- For manual API calls, first request `GET /api/csrf-token` and use returned token in `X-CSRFToken`.
- Verify unauthenticated `POST /api/chat` returns `401`.
- Verify unauthenticated `POST /api/chat/feedback` returns `401`.

### 4.2 UI smoke
- Open homepage.
- Confirm `NTU Pool Assistant` launcher button appears and can open chat panel.
- As guest, open chatbot and confirm input area is replaced by login prompt.
- After login, ask a question and confirm reply/sources render.
- Send a small-talk message like `hi`; confirm reply is returned with empty `sources`.
- Ask one Chinese and one English question; confirm reply language follows input.
- Continue chatting until user cumulative count reaches 10, then confirm 5-star feedback widget appears.
- Submit a star rating and confirm no second submission is allowed for the same message.

## 5. Deploy to Cloud Run

### 5.1 Windows CMD
```bat
deploy_update.bat
```

Environment check only (no build/deploy):
```bat
deploy_update.bat --check-only
```

### 5.2 PowerShell
```powershell
.\deploy_update.bat
```

Deploy scripts behavior:
1. Check required env vars.
2. Run `.venv` doctor precheck (`scripts/venv_doctor.py --require-deploy-tools`).
3. Build container image.
4. Deploy Cloud Run service with chatbot env vars.
5. Output service URL.

Important:
- If you double-click `deploy_update.bat`, it now auto-loads project `.env` variables.
- If `DATABASE_URL` is missing but `SQLALCHEMY_DATABASE_URI` exists, `deploy_update.bat` will use it as fallback.
- If you need a non-default chat log table name, include `SUPABASE_CHAT_LOG_TABLE` explicitly in your deploy command env vars.

## 6. Production Verification Checklist
1. Homepage loads and shows chatbot panel.
2. Guest sees login prompt in chatbot panel (no send textarea).
3. Unauthenticated `POST /api/chat` returns `401`.
4. Unauthenticated `POST /api/chat/feedback` returns `401`.
5. Logged-in `POST /api/chat` returns `200` for valid message.
6. Invalid payload returns `400`.
7. Missing config returns `503`.
8. Unknown question returns polite language-matched fallback text.
9. `sources` contains URLs when retrieval succeeds via RAG.
10. Small-talk input (`hi`, `hello`, `你好`) returns direct chat reply with `sources=[]`.
11. Post/comment/report data queries should route to database tool-use path.
12. Backend rules/config questions (for example lightning logic settings) should route to knowledge path with backend-priority context.
13. Chat input should support `Enter` to send and `Ctrl/Cmd + Enter` for newline.
14. On message count `5/10/15...`, response includes `feedback_required=true` and a valid `conversation_id`.
15. Rating submit to `/api/chat/feedback` stores score successfully.

## 7. Troubleshooting

### 7.1 `ModuleNotFoundError` during ingest
- Ensure dependencies were installed into `.venv`:
  `dev.bat setup`
- Ensure commands are executed with `.venv\Scripts\python.exe` rather than system `python`.

### 7.2 Chat endpoint returns fallback for every question
- Corpus may be too small or score threshold too strict.
- Lower `CHATBOT_MIN_SCORE` (for example `0.45 -> 0.3`) and redeploy.

### 7.3 Intent routing is wrong
- Check `CHATBOT_INTENT_API_KEY`, `CHATBOT_INTENT_BASE_URL`, and `CHATBOT_INTENT_MODEL`.
- Confirm intent model can return valid JSON with intent in:
  `small_talk|database|knowledge_base|fallback`.
- If intent model is unstable, system falls back to local heuristics in `app/services/chatbot/graph.py`.

### 7.4 Backend rules question returns unknown
- Confirm knowledge sync includes `backend_non_sensitive` and `realtime_status_snapshot` documents.
- Ensure latest `graph.py` is deployed; backend rules questions should prioritize runtime/backend snapshot context before generic vector retrieval.

### 7.5 Chat endpoint returns `500` with Supabase vector-store method issues
- Current code has RPC fallback in `graph.py`; ensure latest code is deployed.

### 7.6 CSRF errors (`400 Invalid or missing CSRF token`)
- Frontend sends `X-CSRFToken`, and now auto-refreshes token via `GET /api/csrf-token` with one retry on CSRF `400`.
- For manual API tests, fetch a fresh token from `GET /api/csrf-token` and include it in request headers.

### 7.7 Feedback UI not showing at 10th message
- Confirm chat rows are actually inserted into `chatbot_conversations`.
- Confirm `message_counter` increments per user and `feedback_requested=true` on the 10th row.
- Confirm `/api/chat` response contains `feedback_required=true` and `conversation_id`.

### 7.8 Rating submit fails
- Check `/api/chat/feedback` request carries a valid UUID `conversation_id` and integer `rating` (`1-5`).
- Confirm the row belongs to current user and has `feedback_requested=true`.
- A row can only be rated once (`rating_score` must be null before submit).
