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
- Starts Redis (or detects it's already running)
- Starts the Celery worker (required for background tasks: imports, AI extraction, lead scoring)
- Starts the Flask dev server on http://localhost:5000

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

### Local dev with production data

`flask db upgrade` creates tables only. **Lead data comes from a production database dump** — without it, login works but lists and queues show zero leads.

**Symptoms of an empty local DB:**
- Login succeeds but `/properties` and queues are empty
- `/api/health` reports `lead_visibility: FAIL` (when `HEALTH_CHECK_LEAD_USER_EMAIL` is set)

**Baseline expectations** (after restore): see [`backend/data-snapshot.json`](backend/data-snapshot.json) — e.g. ~75k total leads, ~6.7k for `ben.d.staples.7@gmail.com`.

#### Windows — GitHub Actions (no SSH key on your PC)

1. GitHub → **Actions** → **Download Prod Dump** → **Run workflow** (pick `main` or your branch).
2. When it finishes, open the run → **Artifacts** → download **prod-dump** (contains `prod_dump.dump`).
3. Restore locally:
   ```powershell
   .\scripts\restore-prod-dump.ps1 -DumpFile .\prod_dump.dump
   ```

The workflow uses repository secrets (`VPS_SSH_KEY`, etc.) — you never need to copy the deploy key to this machine.

#### Windows — direct SSH sync (if you have the deploy key)

1. Install the deploy SSH key (one-time) — set `VPS_SSH_KEY_PATH` in `.env`, or:
   ```powershell
   .\scripts\install-deploy-ssh-key.ps1 -KeyFile C:\path\to\bbanalyzer_deploy
   ```

2. Sync production → local PostgreSQL:
   ```powershell
   .\scripts\sync-from-prod.ps1
   ```
   This dumps from the VPS, recreates `real_estate_analysis` locally, restores, and runs `flask db upgrade`.

#### macOS / Linux / Git Bash

1. Copy a VPS backup to `~/prod_for_dev.dump`:
   ```bash
   scp deploy@5.161.200.46:/home/deploy/backups/pre_migration_<latest>.dump ~/prod_for_dev.dump
   ```
2. Auto-restore and migrate:
   ```bash
   bash scripts/pre-flight-data-check.sh
   ```

#### Verification scripts

| Script | Purpose |
|--------|---------|
| [`scripts/pre-flight-data-check.sh`](scripts/pre-flight-data-check.sh) | Restore from `~/prod_for_dev.dump` if &lt; 1,000 leads |
| [`scripts/restore-prod-dump.ps1`](scripts/restore-prod-dump.ps1) | Restore a dump downloaded from GitHub Actions |
| [`scripts/sync-from-prod.ps1`](scripts/sync-from-prod.ps1) | Full Windows sync from live production (requires deploy SSH key) |
| [`scripts/capture-data-snapshot.sh`](scripts/capture-data-snapshot.sh) | Capture lead counts to `backend/data-snapshot.json` |
| [`scripts/verify-data-snapshot.sh`](scripts/verify-data-snapshot.sh) | Fail if counts drop below 90% of snapshot |
| [`scripts/lead-visibility-check.sh`](scripts/lead-visibility-check.sh) | Confirm a user has non-zero owned leads |

**Passwords after restore:** `pg_restore` brings production `users` rows. You may need your **production** password for `ben.d.staples.7@gmail.com`, not the dev placeholders in `.env` comments.

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
