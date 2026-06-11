# Community Bot Posts Implementation Plan

> **For Antigravity:** REQUIRED WORKFLOW: Use `.agent/workflows/execute-plan.md` to execute this plan in single-flow mode.

**Goal:** Build an automated community seed-post workflow that creates 2-6 AI experiment account posts per Singapore day.

**Architecture:** A protected Flask cron endpoint will be called by GitHub Actions on a schedule. The endpoint delegates to a service that maintains bot accounts, computes a daily post target, enforces spacing and rotation rules, selects a persona/template, creates a `Post`, and records an audit log.

**Tech Stack:** Flask, SQLAlchemy, pytest, GitHub Actions scheduled workflows.

---

### Task 1: Bot Data Model Tests

**Files:**
- Create: `tests/test_community_bot_posts.py`
- Modify: `app/models/user.py`
- Create: `app/models/bot.py`
- Modify: `app/models/__init__.py`

**Steps:**
1. Add failing tests for seeding 50 enabled bot accounts and marking backing users as bot accounts.
2. Run `dev.bat test tests/test_community_bot_posts.py -q` and confirm the model/service imports fail.
3. Add `User.is_bot`, `User.bot_persona`, and bot models.
4. Run the targeted tests and confirm they pass.

### Task 2: Posting Service

**Files:**
- Modify: `tests/test_community_bot_posts.py`
- Create: `app/services/community_bot.py`

**Steps:**
1. Add failing tests for daily target generation, cron tick no-op behavior, post creation, and activity logging.
2. Run the targeted test and confirm failures.
3. Implement the minimal service API: `ensure_bot_accounts`, `run_community_post_tick`, `get_or_create_daily_plan`.
4. Run the targeted tests and confirm they pass.

### Task 3: Cron Endpoint

**Files:**
- Modify: `tests/test_community_bot_posts.py`
- Modify: `app/blueprints/cron.py`

**Steps:**
1. Add failing tests for missing secret rejection and authorized tick execution.
2. Run the targeted tests and confirm failures.
3. Add `GET /api/cron/community-posts`.
4. Run the targeted tests and confirm they pass.

### Task 4: Auto-Migration and Scheduler

**Files:**
- Modify: `app/__init__.py`
- Modify: `.env.example`
- Create: `.github/workflows/community-bot-posts.yml`

**Steps:**
1. Add schema ensure tests where practical through app startup.
2. Create bot tables with `checkfirst=True` and add missing user columns on startup.
3. Add a GitHub Actions scheduled workflow that calls the production URL with `CRON_SECRET`.
4. Run focused tests and the broader Python test suite.

