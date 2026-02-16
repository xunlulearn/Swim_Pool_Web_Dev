# Chatbot Deployment Guide

Updated: 2026-02-16

This runbook matches the current NTU Pool codebase and deployment scripts.

## 1. Required Environment Variables

Required:
1. `DATABASE_URL`
2. `OPENAI_API_KEY`
3. `SUPABASE_URL`
4. `SUPABASE_SERVICE_ROLE_KEY`

Optional (defaults in code/deploy scripts):
1. `OPENAI_BASE_URL` (OpenRouter example: `https://openrouter.ai/api/v1`)
2. `OPENAI_CHAT_MODEL` (default `gpt-4o-mini`)
3. `OPENAI_EMBED_MODEL` (default `text-embedding-3-small`)
4. `SUPABASE_DOCS_TABLE` (default `pool_documents`)
5. `SUPABASE_MATCH_FUNCTION` (default `match_documents`)
6. `CHATBOT_TOP_K` (default `3`)
7. `CHATBOT_MIN_SCORE` (default `0.65`)
8. `CHATBOT_MAX_CONTEXT_CHARS` (default `4000`)
9. `NEA_API_KEY` (weather module)
10. `SECRET_KEY` (if missing, deploy script auto-generates)

Practical recommendation:
- With small corpus, set `CHATBOT_MIN_SCORE=0`.

## 2. Supabase Initialization
1. Open Supabase SQL Editor.
2. Run `init_supabase.sql`.
3. Verify:
   - table `pool_documents`
   - function `match_documents`

## 3. Install Dependencies and Run Ingest (CMD)

If global `pip` fails with permission issues, use local target folder.

### 3.1 Clear proxy variables and install locally
Use CMD syntax exactly as below (no spaces before `&&`):

```bat
set HTTP_PROXY=&& set HTTPS_PROXY=&& set ALL_PROXY=&& set GIT_HTTP_PROXY=&& set GIT_HTTPS_PROXY=&& set NO_PROXY=&& python -m pip install --target .pydeps_cmd langchain langgraph langchain-openai langchain-community supabase tiktoken beautifulsoup4
```

### 3.2 Run ingest with local dependency path

```bat
set PYTHONPATH=d:\Swim_Pool_Web_Dev\.pydeps_cmd;%PYTHONPATH%&& python ingest.py
```

Notes:
- `ingest.py` requires `OPENAI_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`.
- Default sitemap is `https://ntupool.org/sitemap.xml`; if unavailable, script falls back to homepage.
- You can provide explicit URLs:

```bat
set PYTHONPATH=d:\Swim_Pool_Web_Dev\.pydeps_cmd;%PYTHONPATH%&& python ingest.py --url https://ntupool.org/ --url https://ntupool.org/social/
```

## 4. Local Smoke Test

### 4.1 API smoke (requires valid CSRF token)
- Start app locally.
- Use browser flow or test client flow that includes `X-CSRFToken`.

### 4.2 UI smoke
- Open homepage.
- Confirm `NTU Pool Assistant` card appears.
- Ask a question and confirm reply/sources render.

## 5. Deploy to Cloud Run

### 5.1 Windows CMD
```bat
deploy_update.bat
```

### 5.2 PowerShell
```powershell
./deploy.ps1
```

Deploy scripts behavior:
1. Check required env vars.
2. Build container image.
3. Deploy Cloud Run service with chatbot env vars.
4. Output service URL.

Important:
- If you double-click `deploy_update.bat`, it reads current process/system environment variables, not `.env` file directly.

## 6. Production Verification Checklist
1. Homepage loads and shows chatbot panel.
2. `POST /api/chat` returns `200` for valid message.
3. Invalid payload returns `400`.
4. Missing config returns `503`.
5. Unknown question returns polite fallback text.
6. `sources` contains URLs when retrieval succeeds.

## 7. Troubleshooting

### 7.1 `ModuleNotFoundError` during ingest
- Ensure `.pydeps_cmd` install succeeded.
- Ensure `PYTHONPATH` includes `.pydeps_cmd` before running script.

### 7.2 Chat endpoint returns fallback for every question
- Corpus may be too small or score threshold too strict.
- Set `CHATBOT_MIN_SCORE=0`, then redeploy.

### 7.3 Chat endpoint returns `500` with Supabase vector-store method issues
- Current code has RPC fallback in `graph.py`; ensure latest code is deployed.

### 7.4 CSRF errors (`400 Invalid or missing CSRF token`)
- Frontend already sends `X-CSRFToken` from meta tag.
- For manual API tests, include a valid token in request headers.
