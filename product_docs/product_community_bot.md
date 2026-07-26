# 2.6 Community Bot System (Ambience Accounts)

## Goal
Keep the community feed and the manual-report feed looking alive while the real user base grows, without ever contradicting reality (no activity while the pool is closed, no "tonight" posts at 9 AM, no bot influence over safety-critical signals).

## Accounts
- 50 persona accounts (20 Chinese, 30 English), each with a stable username `bot_<persona>`, nickname, archetype (`general` / `squad` / `tutorial` / `lostfound`), and generated avatar.
- All bot users carry `users.is_bot = true`. This flag is the single source of truth for every "exclude bots" rule.

## Scheduler (runs on the `/api/cron/community-posts` tick, every 30 min)
1. **Operating-hours gate.** A tick outside the SGT operating window (shared module `app/services/operating_hours.py`, weekday 07:00–21:30, weekend/holiday 08:00–20:00, holidays 2026–2027) does nothing. The window is shrunk by a 30-minute buffer at both ends.
2. **Random in-window distribution.** For each action type the tick fires with probability `remaining_actions / remaining_ticks`, which spreads the daily targets approximately uniformly across the remaining open window instead of burning them right after midnight.
3. **Daily plan** (`bot_daily_post_plans`): posts 2–6, standalone pool reports 3–7, comments 2–5, likes 4–10 per SGT day.
4. **Timestamp scatter.** All bot activity timestamps are shifted back by a random 0–17 minutes so nothing aligns with the :00/:30 cron boundary.

## Content rules
- Post templates are split by time-of-day bucket (morning / midday / evening / any); time-referencing copy ("tonight", "早场") only appears in its own bucket.
- A title used by any bot within the last 10 days is not reused while alternatives exist.
- **LLM variation (2026-07)**: when `COMMUNITY_BOT_LLM_CONTENT` is enabled and `OPENAI_API_KEY` is set, the selected template becomes an *anchor* that the chat model rewrites into a fresh variation (same topic/tone/persona language). Guardrails: 8s timeout, at most ONE LLM call per tick, strict validation (language match, length caps, no recently used title, no planning for a time of day that already passed — a morning post may say "tonight", an evening post may not say "this morning"). Any failure silently falls back to the static template, so the scheduler never depends on the API. `bot_activity_logs.reason` ends with `:llm` or `:template` for auditing. Cost: at most ~9 short gpt-4o-mini calls/day.
- Pool reports are decoupled from posts: different bot, different minute, status mirrors the weather engine ("Open" only when GREEN).

## Interactions
- Comment targets come from the community feed's **first page** (latest 20 non-pinned posts, max 14 days old) — bots react to what a visitor actually sees. Priority: human posts with zero replies, then quiet human posts, then unanswered bot posts. Daily volume 2-4.
- Comments are LLM-composed to react to the post's actual content (same guardrails and static-template fallback as posts; never states current pool conditions as fact, no URLs).
- Comment language always matches the post language; a bot never comments on its own post, at most 2 bot comments per post, and bot likes never duplicate.
- Every action is written to `bot_activity_logs` (`create_post`, `pool_report`, `create_comment`, `like_post`) for auditing and daily counting.

## Legacy data cleanup
- A one-time migration (`dedupe_cleanup` marker in `bot_activity_logs`) soft-deletes duplicate-titled legacy bot posts left over from the small pre-2026-07 template pool. Per title it keeps the human-commented post first, then the most-commented, then the newest; posts with human comments are never hidden. It runs automatically on the first scheduler tick after deploy, before the operating-hours gate.

## Integrity guarantees
- `weather_engine._get_community_consensus()` excludes `is_bot` users: bot reports can neither form nor break the human consensus that overrides weather status.
- The homepage live feed only shows reports from the last 24 hours, so overnight-closed reports can never dominate the next day's view.

## Ops
- GitHub Actions workflow `community-bot-posts.yml` runs only during SGT operating hours (UTC 23:00–13:30); the app-side gate remains the source of truth.
- Note: GitHub disables scheduled workflows after ~60 days without repository activity — keep an eye on the Actions tab.
