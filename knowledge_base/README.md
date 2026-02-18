# Knowledge Base Folder

Put your custom chatbot knowledge files here as Markdown (`.md`) files.

## How It Works

1. Add, edit, or delete Markdown files in this folder.
2. Run `dev.bat sync` in the project root (or double-click `sync_knowledge_base.bat`).
3. The script runs incremental sync by default (new/changed/deleted docs only), so your file changes are reflected in chatbot retrieval without full rewrite.

Maintenance note:
- This project is maintained under `.venv`. Do not run sync with system Python.

## Content Rules

- Keep only non-sensitive information.
- Do not include passwords, API keys, private tokens, or personal secrets.
- Prefer one topic per file for cleaner retrieval.

## File Naming Suggestion

- `pool_rules.md`
- `faq_membership.md`
- `facility_notes_2026-02.md`
