---
trigger: always_on
---

# Technical Stack & Development Rules

## 1. Development Philosophy (Antigravity Agent-First)
* **Workflow**: Always generate an **Implementation Plan** (artifact) before writing complex logic.
* **Trust but Verify**: Critical algorithms (e.g., Lightning Distance) must include unit tests with known coordinates to verify accuracy (error margin < 0.1%).

## 2. Tech Stack Selection

### Backend
* **Language**: Python 3.11+
* **Framework**: Flask (Use Blueprints for modular architecture).
* **Authentication**: Flask-Mail + `itsdangerous` (for tokens).
* **ORM**: SQLAlchemy.
* **Distance Algorithm**: Must use **Haversine Formula** (Great-circle distance), NOT Euclidean distance. Earth Radius R = 6,371 km.

### Frontend
* **Stack**: HTML5 + Vanilla JavaScript + **Tailwind CSS**.
* **Styling**: Use Tailwind utility classes strictly. Avoid custom CSS files to facilitate Browser Agent testing.
* **Layout**: `grid-cols-1` for mobile, `md:grid-cols-3` for desktop.

### Database
* **System**: PostgreSQL.
* **Core Tables**: `Users`, `Posts`, `Comments`, `Friendships` (Self-referencing), `Groups`.

### Infrastructure & DevOps
* **Deployment**: Google Cloud Run (Serverless).
* **Container**: Docker (Multi-stage builds).
* **CI/CD**: Use Antigravity MCP for deployment commands.

## 3. Coding Standards
* **Error Handling**: Weather API polling must handle Rate Limits (429) and Timeouts gracefully without crashing the app.
* **Documentation**: All functions must have docstrings explaining inputs and outputs.