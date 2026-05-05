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

# Run development server
python backend/run.py

# Run tests
cd backend && pytest

# Run specific test file
cd backend && pytest tests/test_lead_controller.py -v
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

## Environment

- Backend config via `backend/.env` (see `backend/.env.example` for required variables)
- Frontend config via `frontend/.env` (uses `VITE_` prefix for env vars)
- Database URL defaults to `postgresql://localhost/real_estate_analysis`
- Redis URL defaults to `redis://localhost:6379/0`
