# Tech Stack & Build

## Backend (Python / Flask)

- **Framework**: Flask 3.0 with application factory pattern (`create_app` in `backend/app/__init__.py`)
- **Database**: PostgreSQL via Flask-SQLAlchemy (SQLite in-memory for tests)
- **Migrations**: Alembic via Flask-Migrate, stored in `backend/alembic_migrations/`
- **Validation**: Marshmallow schemas in `backend/app/schemas.py`
- **Task Queue**: Celery with Redis broker (used for bulk operations like lead rescoring)
- **Rate Limiting**: Flask-Limiter
- **Testing**: pytest + Hypothesis (property-based testing)
- **Key Libraries**: psycopg2-binary, openpyxl (Excel export), google-api-python-client (Sheets integration), requests, cryptography

## Frontend (TypeScript / React)

- **Framework**: React 18 with TypeScript 5
- **Build Tool**: Vite 5 (dev server on port 3000, proxies `/api` to backend on port 5000)
- **UI Library**: MUI (Material UI) v5 with Emotion
- **Routing**: React Router v6
- **Data Fetching**: TanStack React Query v5 + Axios
- **Charts**: Recharts
- **Testing**: Vitest + React Testing Library + jsdom
- **Path Alias**: `@` maps to `frontend/src/`

## Common Commands

### Backend
```bash
# Install dependencies
pip install -r backend/requirements.txt

# Run development server (from project root OR from backend/ directory)
python backend/run.py
# OR
cd backend && python run.py

# Run tests
cd backend && pytest

# Run specific test file
cd backend && pytest tests/test_lead_controller.py -v

# Optional: Start Redis and Celery worker for async comparable search
# (Not required - comparable search runs synchronously by default)
docker compose up -d
```

### Frontend
```bash
# Install dependencies
cd frontend && npm install

# Run development server
cd frontend && npm run dev

# Build for production
cd frontend && npm run build

# Run tests (single run)
cd frontend && npm test

# Run tests in watch mode
cd frontend && npm run test:watch
```

## Async Processing (Optional)

By default, the comparable search (Step 2 of the analysis workflow) runs **synchronously** 
for easier local development. This means it works immediately without any infrastructure setup.

To enable **async mode** for better performance in production:

1. Start Redis and Celery worker:
   ```bash
   docker compose up -d
   ```

2. Set environment variable in `backend/.env`:
   ```
   USE_ASYNC_COMPARABLE_SEARCH=true
   ```

3. Restart the backend server

**Async mode benefits**: Non-blocking API responses, better for multiple concurrent users  
**Sync mode benefits**: Zero infrastructure required, works out of the box

## Environment

- Backend config via `backend/.env` (see `backend/.env.example` for required variables)
- Frontend config via `frontend/.env` (uses `VITE_` prefix for env vars)
- Database URL defaults to `postgresql://localhost/real_estate_analysis`
- Redis URL defaults to `redis://localhost:6379/0`

## Debugging UI Issues

Before using Puppeteer to investigate a UI problem, follow this order:

1. **Read the component code** — the answer is usually visible directly in the JSX.
   For the analysis workflow, all step rendering is in `frontend/src/App.tsx` (`AnalysisRoute`).

2. **Check backend logs** — use `get_process_output` on the backend process to see
   API errors, SQL errors, and step transitions without launching a browser.

3. **Run the relevant tests** — `cd frontend && npm test -- AnalysisRoute` will show
   exactly which step assertions fail and what content is missing.

4. **Check the browser console** — `AnalysisRoute` logs step state in dev mode:
   ```
   [AnalysisRoute] step=WEIGHTED_SCORING (4)
     subject_property: 1234 W Lunt Ave...
     ranked_comparables: 4
     valuation_result: null
     step_results keys: [COMPARABLE_SEARCH]
   ```
   This immediately shows whether data is missing from the API or just not rendered.

**Use Puppeteer only** for issues that require visual confirmation or user interaction
that cannot be determined from code, logs, or tests alone (e.g. layout bugs, animation
timing, autocomplete behaviour).
