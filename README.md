# NTU Swimming Pool Website

[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.x-000000?logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Database-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![LangChain](https://img.shields.io/badge/LangChain-RAG-1C3C3C)](https://www.langchain.com/)
[![Deploy](https://img.shields.io/badge/Deploy-Vercel-000000?logo=vercel&logoColor=white)](https://vercel.com)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-666666)](#getting-started)

A comprehensive platform for Nanyang Technological University (NTU) students and staff to track real-time swimming pool status and connect with the community.

## Overview

This project reduces uncertainty in pool availability caused by weather or maintenance. It combines official meteorological data with crowdsourced reports to provide accurate status updates, and includes a social hub for swimmers.

## Key Features

### 1. Real-Time Pool Status (Dual-Validation System)

The system uses cross-validation for better reliability:
- Source A (Official): real-time lightning/rainfall related weather data via NEA APIs.
- Source B (Crowdsourced): user-submitted live pool open/closed reports.

### 1.1 Lightning Trend Chart

The home page includes a lightning trend panel backed by `/weather/lightning-history`.
- Distance filters: `15 km` and `30 km` from NTU SRC.
- Time filters: `20 min`, `1 hour`, and `12 hours`.
- Refresh cadence: synchronized with status card and radar at `60 seconds`.
- Chart behavior:
  - `20 min` and `1 hour`: one bar per persisted lightning snapshot.
  - `12 hours`: 60 fixed time bins plus an explicit window-start anchor (61 labels/bars total) so the axis spans exactly 12 hours.
  - Bars only (no fitted smoothing line).
  - Window boundaries are padded so first and last labels align with the selected time range.
- Consistency model:
  - The latest snapshot point is aligned with the same shared lightning snapshot used by `/weather/status` and `/weather/lightning-radar`.
- Data source metadata is returned in API payload and can be `persisted_store`, `live_api`, `sample_data`, or `degraded`.

### 1.2 Lightning Radar Map

The home page also includes a radar-style lightning map backed by `GET /weather/lightning-radar`.
- Rendering model:
  - Radar grid and sweep use layered HTML5 canvas.
  - Lightning points are DOM elements so each point can pulse and be highlighted independently.
- Visual behavior:
  - Points pulse continuously in red (`breathe` animation).
  - When the sweep head crosses a point angle, the point briefly switches to a white highlighted state (`scanned` class), then returns to red pulse.
- Data and range:
  - Uses the latest lightning snapshot centered on NTU SRC.
  - Radar rings represent `7.5 km`, `15 km`, `22.5 km`, and `30 km`.
  - Status card lightning metrics and radar metrics now use the same latest snapshot basis (`30 km around NTU SRC`).
  - API metadata follows the same source model (`persisted_store`, `live_api`, `sample_data`, `degraded`) as other weather endpoints.

### 2. Social Community

A dedicated space for NTU swimmers:
- Users can create posts, comments, and likes.
- Keyword search across post titles and bodies (works with category filters).
- Users can find swimming partners and organize meetups.
- Lost-and-found communication support.
- Profile customization (avatar and nickname).
- Ambience bot accounts post, report, comment, and like — only during pool
  operating hours, randomly spread across the day, excluded from status
  consensus (see `product_docs/product_community_bot.md`).

## User Roles and Permissions

| Feature | Guest (Unregistered) | Verified User (Logged In) |
| :--- | :---: | :---: |
| View Pool Status | Yes | Yes |
| Report Pool Status | No | Yes |
| Browse Community Feed | Yes | Yes |
| Create Posts | No | Yes |
| Comment and Like | No | Yes |
| Profile Management | No | Yes |
| Chatbot Assistant | No | Yes |

## Tech Stack

- Backend: Python, Flask
- Database: PostgreSQL
- External API: NEA Weather API (`https://api-open.data.gov.sg/v2/real-time/api/weather?api=lightning`)
- Frontend: HTML/CSS (mobile-first)

## Development Environment Policy

For long-term maintenance, use the project virtual environment `.venv` as the single Python runtime for all development tasks:
- dependency install
- app startup
- tests
- chatbot knowledge sync
- database scripts
- deploy prechecks

Do not rely on system/global Python for routine project updates.

## Getting Started

### Prerequisites

- Python 3.12+
- pip
- Git

Optional system tools (not Python packages, validated by `dev.bat doctor`):
- GitHub CLI (`gh`) for release publishing
- Node.js/npm (`npx`) for Vercel CLI deployment

### Installation

1. Clone the repository
```bash
git clone https://github.com/YourUsername/Swim_Pool_Web_Dev.git
cd Swim_Pool_Web_Dev
```

2. Set up environment file
```bash
# Windows
copy .env.example .env

# Mac/Linux
cp .env.example .env
```

3. Create `.venv`
```bash
# Windows
python -m venv .venv

# Mac/Linux
python3 -m venv .venv
```

4. Install dependencies into `.venv`
```bash
# Windows
.venv\Scripts\python.exe -m pip install -r requirements.txt

# Mac/Linux
.venv/bin/python -m pip install -r requirements.txt
```

Windows shortcut:
```bat
dev.bat setup
```

5. Initialize database
```bash
# Windows
dev.bat init-db

# Mac/Linux
.venv/bin/python init_db.py
```

6. Run application
```bash
# Windows
dev.bat run

# Mac/Linux
.venv/bin/python -m flask run
```

Visit `http://127.0.0.1:5000`.

### Local Browser Test (Codex Runbook)

When you ask Codex to "test in local browser", use this exact fallback-first sequence:

1. Check whether a local server is already listening:
```bat
netstat -ano | findstr :5000
netstat -ano | findstr :5001
```
2. If not listening, start the app with `run_server.py` (this project binds to `5001`):
```bat
dev.bat run-server
```
3. Verify health before asking user to open browser:
```bat
curl.exe -I http://127.0.0.1:5001
```
4. Give the user the working URL:
```text
http://127.0.0.1:5001
```

Notes:
- `run_server.py` is currently configured with `app.run(port=5001, debug=True)`.
- `dev.bat run` (Flask default) typically serves `http://127.0.0.1:5000`.
- If environment policy blocks programmatic browser launch, provide verified URL directly.

## Daily Maintenance (Windows)

Use the unified project entrypoint:

```bat
dev.bat <command>
```

Common commands:
- `dev.bat setup`
- `dev.bat doctor --strict`
- `dev.bat doctor --require-release-tools`
- `dev.bat doctor --require-deploy-tools`
- `deploy_update.bat --check-only`
- `deploy_update.bat`
- `dev.bat run`
- `dev.bat test -q`
- `dev.bat init-db`
- `dev.bat reset-db`
- `dev.bat sync --debug-query "泳池什么时候开放"`
- `dev.bat sync --full-rebuild`
- `dev.bat git-push "chore(repo): your message"`


## Scheduled Workflows (GitHub Actions)

Two workflows drive background activity. Both call authenticated cron
endpoints with `Authorization: Bearer $CRON_SECRET`:

| Workflow | Schedule (UTC) | Endpoint | Secrets |
| :--- | :--- | :--- | :--- |
| `community-bot-posts.yml` | `*/30 23 * * *` + `*/30 0-13 * * *` (SGT operating hours only) | `/api/cron/community-posts` | `COMMUNITY_BOT_CRON_URL`, `CRON_SECRET` |
| `collect-lightning.yml` | `*/10 * * * *` | `/api/cron/collect-lightning` | `LIGHTNING_CRON_URL`, `CRON_SECRET` |

Notes:
- The community bot scheduler is additionally gated in the app: outside the
  buffered SGT operating window every tick is a no-op, and daily targets are
  spread randomly across the open window.
- `collect-lightning.yml` exists because the in-process collector thread does
  not survive on Vercel serverless; without it the 12-hour lightning chart
  develops gaps whenever nobody is browsing.
- GitHub disables scheduled workflows after ~60 days without repo activity;
  re-enable them from the Actions tab if pushes have been quiet.

## Weather Engine Runtime Flags

The following environment variables control weather data behavior:
- `USE_SAMPLE_WEATHER_DATA` (`true`/`false`): enables sample weather payloads in DEBUG/TESTING only.
- `FORCE_SAMPLE_WEATHER_DATA` (`true`/`false`): forces sample mode regardless of environment (local review helper).
- `WEATHER_STATUS_CACHE_SECONDS`: cache TTL for `/weather/status` responses (default `30`).
- `WEATHER_API_TIMEOUT_SECONDS`: per-request timeout for upstream NEA weather API calls (default `4`).
- `LIGHTNING_SNAPSHOT_CACHE_SECONDS`: cache TTL for shared latest lightning snapshot used by status/radar/history alignment (default `30`).
- `LIGHTNING_HISTORY_CACHE_SECONDS`: cache TTL for `/weather/lightning-history` responses (default `60`).
- `LIGHTNING_COLLECTOR_ENABLED`: start background lightning collector thread (default `true`).
- `LIGHTNING_COLLECTOR_INTERVAL_SECONDS`: collector interval in seconds (default `120`).
- `LIGHTNING_COLLECTOR_STARTUP_DELAY_SECONDS`: startup delay before first collection tick (default `5`).

Lightning snapshots are persisted in `lightning_history_snapshots` and used as the source of truth for:
- status card (`/weather/status`)
- radar (`/weather/lightning-radar`)
- trend chart (`/weather/lightning-history`)

DB egress guardrails (behavior-preserving optimizations):
- `/api/live-status/` reads only `pool_reports.id/status/created_at` + `users.username` for the latest 10 rows, avoiding avatar/blob columns.
- Lightning history aggregation reads only metric columns needed for chart bins.
- Latest lightning snapshot loading avoids `source_record_json` unless fallback reconstruction is truly needed.

PowerShell 5.1 compatibility:
- Avoid chaining with `&&` in this repo's Windows shell context.
- Use separate lines, `;`, or use `dev.bat` wrappers.

## Contribution

Contributions are welcome. Please submit issues or pull requests.

## License

This project is licensed under the MIT License.

## Chatbot Deployment

For Vercel and LangGraph/LangChain chatbot deployment details, see
`VERCEL_DEPLOY.md` and `CHATBOT_DEPLOY.md`.

## Chatbot Runtime Behavior

1. The chatbot panel is visible globally on all pages that extend the base template.
2. Only logged-in users can send chatbot messages. Guests see a login prompt in the panel.
3. Every successful chatbot exchange is persisted to Supabase table `chatbot_conversations`.
4. On every 5th cumulative message per user (5/10/15...), the assistant includes a 5-star rating widget.
5. Chatbot uses intent-first routing:
   - `small_talk`: direct LLM reply
   - `database`: function calling/tool-use against app DB, then LLM summary
   - `knowledge_base`: RAG retrieval + LLM generation
   - `fallback`: out-of-scope fallback reply
6. Backend rules/config questions (for example lightning/rain thresholds, persistence windows, consensus logic, runtime settings) use backend-priority context in knowledge path.
7. Casual small-talk (`hi`, `hello`) bypasses vector retrieval and uses direct LLM chat.
8. Reply language follows user input language.
9. Chat input behavior: `Enter` sends message, `Ctrl/Cmd + Enter` inserts newline.
10. When knowledge retrieval is used, `sources` are returned if available.
11. Translation pipeline for non-English input uses intent model first, then falls back to QA model if the primary translation fails.
12. Every model invocation failure is logged to Supabase tables:
   - `chatbot_intent_model_failures`
   - `chatbot_qa_model_failures`
13. Browser chat flows recover from stale CSRF tokens by requesting `GET /api/csrf-token` and retrying once on CSRF `400`.
14. Per-user rate limits protect the LLM budget: burst limit (default 8 msg/min) and daily cap (default 80/day, counted via Supabase, fail-open). HTTP 429 with a bilingual message when exceeded.
15. Routing is heuristic-first: the external intent model is only consulted for ambiguous messages (10s timeout). Answers are generated directly in the user's language; no upfront translation step.
16. A hard knowledge base of 50 curated bilingual Q&A entries answers matching questions directly with zero model calls (~1 ms). Live-status and record-lookup questions are deliberately excluded and keep using the live pipeline.
17. Every reply returns 3 clickable suggested questions drawn from the hard knowledge base; clicking one answers instantly.

## Chatbot Knowledge Sync

To keep chatbot retrieval data up to date:

1. Put Markdown files under `knowledge_base/`.
2. Run `dev.bat sync` (or double-click `sync_knowledge_base.bat`, which calls the same `.venv` path).
3. Incremental sync updates vector rows from:
   - `ntupool.org` sitemap pages
   - runtime pool status + manual reports
   - community posts/comments
   - backend non-sensitive config snapshot
   - local Markdown files in `knowledge_base/`

Force full refresh when needed:
```bash
# Windows
dev.bat sync --full-rebuild

# Mac/Linux
.venv/bin/python sync_knowledge_base.py --full-rebuild
```
