# NTU Pool Web FileSpec

Last Updated: 2026-02-18
Purpose: Fast navigation for feature work and bug fixes. Keep this file short and action-oriented.

## 1. Start Here
- App entry: `app/__init__.py` (`create_app`, blueprint registration, CSRF, production guards)
- Config source: `app/config.py` + project `.env`
- Shared layout: `app/templates/base.html`
- Chatbot frontend: `app/static/js/chatbot.js`
- Maintenance entrypoint (Windows): `dev.bat`
- Environment doctor: `scripts/venv_doctor.py`

## 2. Feature-to-File Routing
- Weather API/UI:
  - Backend: `app/blueprints/weather.py`
  - Engine logic: `app/services/weather_engine.py`
  - Frontend: `app/static/js/weather.js`, `app/static/js/weather_v2.js`
- Chatbot:
  - API routes: `app/blueprints/chatbot.py`
  - Core graph/RAG/intent: `app/services/chatbot/graph.py`
  - Frontend widget: `app/static/js/chatbot.js`
  - UI mount point: `app/templates/base.html`
- Live status:
  - Backend: `app/blueprints/live_status.py`
  - Frontend: `app/static/js/live_status.js`
- Auth/social/misc pages:
  - `app/blueprints/auth.py`, `app/blueprints/social.py`, `app/blueprints/misc.py`

## 3. Data and Ingestion
- Supabase schema and SQL objects: `init_supabase.sql`
- Knowledge sync (primary): `sync_knowledge_base.py`
- Legacy ingest script: `ingest.py`
- Local docs source: `knowledge_base/`

## 4. Deploy and Runtime Constraints
- Deploy script: `deploy_update.bat`
- Deploy scripts require local `.venv` precheck via `scripts/venv_doctor.py --require-deploy-tools`.
- Required env (typical):
  - `DATABASE_URL`
  - `OPENAI_API_KEY`
  - `SUPABASE_URL`
  - `SUPABASE_SERVICE_ROLE_KEY`
- Chatbot behavior depends on env in `app/config.py`; verify there first when issues look "random".

## 5. Test Map
- API/integration style tests: `tests/test_chatbot_api.py`
- Graph/routing logic tests: `tests/test_chatbot_graph.py`

## 6. High-Risk Files (Edit Carefully)
- `app/services/chatbot/graph.py`: mixed intent routing + retrieval + fallback logic
- `app/blueprints/chatbot.py`: input validation, auth enforcement, persistence, feedback flow
- `app/__init__.py`: app boot and global middleware behavior
- `init_supabase.sql`: schema changes can break runtime + ingestion

## 7. Fast Search Hints
- Route definitions: `rg "@.*route\(" app/blueprints`
- Chatbot API flow: `rg "api/chat|feedback|conversation_id" app/blueprints/chatbot.py app/static/js/chatbot.js`
- Intent/RAG path: `rg "intent|retrieve|fallback|similarity|rpc" app/services/chatbot/graph.py`
- Env usage: `rg "os\.getenv|config\[|current_app\.config" app`

## 8. Maintenance Rule
Only update this file when one of these changes:
- File ownership/responsibility changed
- New critical entrypoint added
- High-risk edit path changed
- Deploy-critical env dependency changed

Do not duplicate full API contracts or long architecture prose here; keep detailed behavior in code/tests/docs close to implementation.

## 9. Local Browser Test Runbook (Use By Default)
- Goal: user says "open local browser test", assistant must provide a verified working localhost URL.
- Required execution order:
  - Check listeners: `netstat -ano | findstr :5000` and `netstat -ano | findstr :5001`
  - If no listener, start app with `dev.bat run-server`
  - Verify server with `curl.exe -I http://127.0.0.1:5001`
  - Return URL to user: `http://127.0.0.1:5001`
- Port rule for this repo:
  - `run_server.py` binds `5001`
  - `dev.bat run` usually binds `5000`
- If browser launch is blocked by policy, do not stop at "cannot open"; always start service + verify URL and ask user to open that URL.
