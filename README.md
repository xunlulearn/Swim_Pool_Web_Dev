# NTU Swimming Pool Website

A comprehensive platform for Nanyang Technological University (NTU) students and staff to track real-time swimming pool status and connect with the community.

## Overview

This project reduces uncertainty in pool availability caused by weather or maintenance. It combines official meteorological data with crowdsourced reports to provide accurate status updates, and includes a social hub for swimmers.

## Key Features

### 1. Real-Time Pool Status (Dual-Validation System)

The system uses cross-validation for better reliability:
- Source A (Official): real-time lightning/rainfall related weather data via NEA APIs.
- Source B (Crowdsourced): user-submitted live pool open/closed reports.

### 2. Social Community

A dedicated space for NTU swimmers:
- Users can create posts, comments, and likes.
- Users can find swimming partners and organize meetups.
- Lost-and-found communication support.
- Profile customization (avatar and nickname).

## User Roles and Permissions

| Feature | Guest (Unregistered) | Verified User (Logged In) |
| :--- | :---: | :---: |
| View Pool Status | Yes | Yes |
| Report Pool Status | No | Yes |
| Browse Community Feed | Yes | Yes |
| Create Posts | No | Yes |
| Comment and Like | No | Yes |
| Profile Management | No | Yes |
| Chatbot Assistant | Login prompt only | Chat + 5-star feedback |

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

Do not rely on system/global Python for routine project updates.

## Getting Started

### Prerequisites

- Python 3.12+
- pip

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

5. Initialize database
```bash
# Windows
.venv\Scripts\python.exe init_db.py

# Mac/Linux
.venv/bin/python init_db.py
```

6. Run application
```bash
# Windows
.venv\Scripts\python.exe -m flask run

# Mac/Linux
.venv/bin/python -m flask run
```

Visit `http://127.0.0.1:5000`.

## Contribution

Contributions are welcome. Please submit issues or pull requests.

## License

This project is licensed under the MIT License.

## Chatbot Deployment

For LangGraph/LangChain chatbot deployment details, see `CHATBOT_DEPLOY.md`.

## Chatbot Runtime Behavior

1. The chatbot panel is visible globally on all pages that extend the base template.
2. Only logged-in users can send chatbot messages. Guests see a login prompt in the panel.
3. Every successful chatbot exchange is persisted to Supabase table `chatbot_conversations`.
4. On every 10th cumulative message per user (10/20/30...), the assistant includes a 5-star rating widget.
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

## Chatbot Knowledge Sync

To keep chatbot retrieval data up to date:

1. Put Markdown files under `knowledge_base/`.
2. Double-click `sync_knowledge_base.bat`.
3. Incremental sync updates vector rows from:
   - `ntupool.org` sitemap pages
   - runtime pool status + manual reports
   - community posts/comments
   - backend non-sensitive config snapshot
   - local Markdown files in `knowledge_base/`

Force full refresh when needed:
```bash
# Windows
.venv\Scripts\python.exe sync_knowledge_base.py --full-rebuild

# Mac/Linux
.venv/bin/python sync_knowledge_base.py --full-rebuild
```
