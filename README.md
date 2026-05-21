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
