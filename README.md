# Real Estate Analysis Platform

A web-based application for automated property valuation and investment analysis.

## Project Structure

```
.
├── backend/                 # Flask backend application
│   ├── app/
│   │   ├── __init__.py     # Application factory
│   │   ├── models/         # SQLAlchemy models
│   │   ├── services/       # Business logic services
│   │   └── controllers/    # API route controllers
│   ├── tests/              # Backend tests
│   ├── requirements.txt    # Python dependencies
│   └── run.py             # Application entry point
│
└── frontend/               # React frontend application
    ├── src/
    │   ├── components/     # React components
    │   ├── services/       # API service layer
    │   ├── types/          # TypeScript type definitions
    │   └── main.tsx        # Application entry point
    └── package.json        # Node.js dependencies

```

## Setup Instructions

### Prerequisites

- Python 3.10+
- Node.js 18+
- PostgreSQL 14+
- Redis 6+

### Backend Setup

1. Create and activate Python virtual environment:
```bash
cd backend
python -m venv venv
# Windows
venv\Scripts\activate
# Unix/MacOS
source venv/bin/activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Configure environment variables:
```bash
copy .env.example .env
# Edit .env with your configuration
```

4. Apply database migrations:
```bash
flask db upgrade
```

### Running the Full Dev Environment

Use the single-command launcher from the **project root** — it starts Redis, the Celery worker, and Flask automatically:

```bash
python dev.py
```

This is the **recommended way** to run the app locally. It handles everything:
- Ensures local PostgreSQL has production lead data (auto-downloads via GitHub Actions if empty)
- Starts Redis (or detects it's already running)
- Starts the Celery worker (required for background tasks: imports, AI extraction, lead scoring)
- Starts the Flask dev server on http://localhost:5000

**One-time prerequisite:** authenticate GitHub CLI so prod dumps can be fetched unattended:
```bash
gh auth login
```

No manual dump download or restore commands — `dev.py` runs `scripts/ensure-local-prod-data.ps1` (Windows) or `scripts/ensure-local-prod-data.sh` (macOS/Linux) automatically when lead count is below 1,000.

Then in a separate terminal, start the frontend:
```bash
cd frontend
npm install
npm run dev
```

The frontend will run on http://localhost:3000

> **Note:** Do not use `python backend/run.py` directly — it starts Flask but not the Celery worker, so background tasks (HubSpot imports, OM PDF processing, bulk lead rescoring) will queue but never execute.

### Database Setup

1. Create PostgreSQL database:
```sql
CREATE DATABASE real_estate_analysis;
```

2. Run migrations:
```bash
flask db upgrade
```

### Local dev with production data (fully automated)

`flask db upgrade` creates tables only. Lead data is copied from production automatically when you run `python dev.py`.

| Component | Role |
|-----------|------|
| [`scripts/ensure-local-prod-data.ps1`](scripts/ensure-local-prod-data.ps1) | Windows — called by `dev.py`; uses cached dump, GitHub Actions artifact, or SSH |
| [`scripts/ensure-local-prod-data.sh`](scripts/ensure-local-prod-data.sh) | macOS/Linux — same behavior |
| [Download Prod Dump](.github/workflows/download-prod-dump.yml) | Nightly + on-demand `pg_dump` on GitHub Actions (uses repo secrets) |
| [`scripts/restore-prod-dump.ps1`](scripts/restore-prod-dump.ps1) | Internal restore helper (you do not need to run this manually) |

**Requirements (once per machine):**
- PostgreSQL running on `localhost:5432` (see `DATABASE_URL` in `.env`)
- `gh auth login` (GitHub CLI) — repo access for `bendstaples7/B-B-Commercial-RE-Underwriting`

**Optional — refresh data while logged out of the IDE:**
```powershell
# Windows Task Scheduler: daily at 3 AM + at logon
.\scripts\ensure-local-prod-data.ps1 -Install
```
```bash
# macOS/Linux cron: daily at 3 AM
bash scripts/ensure-local-prod-data.sh --install
```

Baseline after restore: see [`backend/data-snapshot.json`](backend/data-snapshot.json) (~75k leads total).

### Redis Setup

Redis is started automatically by `python dev.py`. If you need to run it manually, ensure Redis is running on localhost:6379 or configure `REDIS_URL` in `.env`.

## Running Tests

### Backend Tests
```bash
cd backend
pytest
```

### Frontend Tests
```bash
cd frontend
npm test
```

## Development Workflow

1. Backend API development in `backend/app/`
2. Frontend component development in `frontend/src/`
3. Run both servers concurrently for full-stack development
4. API requests from frontend are proxied to backend via Vite

## Technology Stack

**Backend:**
- Flask (web framework)
- SQLAlchemy (ORM)
- PostgreSQL (database)
- Redis (caching)
- Celery (async tasks)
- pytest + hypothesis (testing)

**Frontend:**
- React 18 + TypeScript
- Material-UI (components)
- React Query (state management)
- Recharts (visualization)
- Vite (build tool)
