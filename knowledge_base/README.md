# Knowledge Base Folder

Put your custom chatbot knowledge files here as Markdown (`.md`) files.

## How It Works

1. Add, edit, or delete Markdown files in this folder.
2. Double-click `sync_knowledge_base.bat` in the project root.
3. The script runs incremental sync by default (new/changed/deleted docs only), so your file changes are reflected in chatbot retrieval without full rewrite.

## Content Rules

- Keep only non-sensitive information.
- Do not include passwords, API keys, private tokens, or personal secrets.
- Prefer one topic per file for cleaner retrieval.

## File Naming Suggestion

- `pool_rules.md`
- `faq_membership.md`
- `facility_notes_2026-02.md`
