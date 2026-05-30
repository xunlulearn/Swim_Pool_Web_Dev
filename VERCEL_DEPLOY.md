# Vercel Deployment Guide

This project can run on Vercel as a Python Flask function through
`vercel_app.py`. The always-on
Cloud Run lightning collector is replaced by an authenticated HTTP cron
endpoint that an external scheduler calls periodically.

## 1. Vercel Environment Variables

Set these variables in Vercel Project Settings:

Required:
- `FLASK_ENV=production`
- `FLASK_CONFIG=production`
- `SECRET_KEY`
- `DATABASE_URL`
- `CRON_SECRET`

Recommended for Vercel:
- `LIGHTNING_COLLECTOR_ENABLED=false`
- `USE_SAMPLE_WEATHER_DATA=false`
- `WEATHER_STATUS_CACHE_SECONDS=30`
- `LIGHTNING_SNAPSHOT_CACHE_SECONDS=30`
- `LIGHTNING_HISTORY_CACHE_SECONDS=60`
- `DB_CONNECT_TIMEOUT=5`
- `DB_STATEMENT_TIMEOUT_MS=8000`
- `DB_POOL_TIMEOUT=10`
- `DB_POOL_RECYCLE=1800`

Feature variables:
- `NEA_API_KEY`
- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_CHAT_MODEL`
- `OPENAI_EMBED_MODEL`
- `CHATBOT_INTENT_API_KEY`
- `CHATBOT_INTENT_BASE_URL`
- `CHATBOT_INTENT_MODEL`
- `SUPABASE_URL`
- `SUPABASE_SERVICE_ROLE_KEY`
- `SUPABASE_DOCS_TABLE`
- `SUPABASE_MATCH_FUNCTION`
- `SUPABASE_CHAT_LOG_TABLE`
- `SUPABASE_INTENT_LLM_FAILURE_TABLE`
- `SUPABASE_QA_LLM_FAILURE_TABLE`
- `CHATBOT_TOP_K`
- `CHATBOT_MIN_SCORE`
- `CHATBOT_MAX_CONTEXT_CHARS`
- `CHATBOT_DB_TOOL_MAX_CALLS`

## 2. Generate Secrets

Use long random values. Do not commit them to git.

PowerShell:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Generate one value for `SECRET_KEY` and another for `CRON_SECRET`.

## 3. Deploy to Vercel

1. Import the GitHub repository in Vercel.
2. Add the environment variables above.
3. Deploy.
4. Confirm the homepage loads.
5. Confirm the cron endpoint rejects public access:

```text
https://YOUR_DOMAIN/api/cron/collect-lightning
```

Expected response:

```json
{"error":"Not found."}
```

6. Confirm the cron endpoint works with the secret:

```text
https://YOUR_DOMAIN/api/cron/collect-lightning?secret=YOUR_CRON_SECRET
```

Expected response:

```json
{"ok":true}
```

## 4. Configure cron-job.org

Create a cron-job.org job:

- URL: `https://YOUR_DOMAIN/api/cron/collect-lightning?secret=YOUR_CRON_SECRET`
- Method: `GET`
- Schedule: every 2 minutes
- Timeout: default is fine
- Failure notifications: enabled

The endpoint returns a short JSON response so it stays within cron-job.org's
30-second execution limit.

## 5. Runtime Model

On Cloud Run, the app used an in-process background thread to collect lightning
snapshots every 120 seconds. On Vercel, functions are started on demand and may
be frozen after a request, so long-running background threads are not reliable.

With this setup:
- Vercel serves the website and Flask API.
- `LIGHTNING_COLLECTOR_ENABLED=false` prevents an unreliable background thread.
- cron-job.org calls `/api/cron/collect-lightning` every 2 minutes.
- The endpoint stores lightning snapshots in the existing database.
- `/weather/lightning-history` continues to read persisted snapshot history.
