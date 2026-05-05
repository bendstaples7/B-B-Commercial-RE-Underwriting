# Project Structure

Monorepo with `backend/` (Python/Flask) and `frontend/` (React/TypeScript).

## Backend (`backend/`)

```
backend/
├── run.py                      # Entry point — runs Flask dev server on port 5000
├── celery_worker.py            # Celery worker entry point
├── requirements.txt            # Python dependencies
├── pytest.ini                  # pytest config (testpaths = tests, -v --tb=short)
├── .env / .env.example         # Environment variables
├── app/
│   ├── __init__.py             # App factory (create_app), db/migrate/limiter init
│   ├── controllers/            # Flask Blueprints — route handlers
│   │   ├── __init__.py         # Registers api_bp blueprint
│   │   ├── routes.py           # Core analysis workflow endpoints (/api/analysis/*)
│   │   ├── lead_controller.py  # Lead CRUD + scoring (/api/leads/*)
│   │   ├── import_controller.py        # Google Sheets import (/api/leads/import/*)
│   │   ├── enrichment_controller.py    # Data enrichment (/api/leads/*/enrich)
│   │   ├── marketing_controller.py     # Marketing lists (/api/leads/marketing/*)
│   │   └── workflow_controller.py      # Analysis workflow state machine
│   ├── models/                 # SQLAlchemy models (one model per file)
│   ├── services/               # Business logic (one service per file)
│   ├── schemas.py              # Marshmallow request/response schemas (single file)
│   ├── exceptions.py           # Custom exception hierarchy (base: RealEstateAnalysisException)
│   ├── error_handlers.py       # Global Flask error handlers
│   ├── api_utils.py            # Shared API utilities
│   └── logging_config.py       # Logging setup
├── alembic_migrations/         # Alembic migration scripts
├── migrations/                 # Raw SQL migration files
├── tests/                      # pytest test suite
│   ├── conftest.py             # Fixtures (app, client, seeded_app, mock_apis)
│   ├── test_*.py               # Test files follow test_<module>.py naming
│   ├── mock_apis.py            # Mock external API factory
│   └── e2e_setup.py            # E2E test data seeding
└── logs/                       # Runtime log files
```

## Frontend (`frontend/`)

```
frontend/
├── package.json                # Dependencies and scripts
├── vite.config.ts              # Vite config (port 3000, API proxy, @ alias, vitest)
├── index.html                  # HTML entry point
├── src/
│   ├── main.tsx                # React root — QueryClient, ThemeProvider, BrowserRouter
│   ├── App.tsx                 # Top-level routing and layout (sidebar + routes)
│   ├── components/             # React components (one component per file, .tsx)
│   ├── services/
│   │   └── api.ts              # Axios instance + service methods
│   ├── types/
│   │   └── index.ts            # All TypeScript interfaces and enums
│   └── test/
│       └── setup.ts            # Vitest setup (jest-dom, matchMedia/ResizeObserver mocks)
└── public/images/              # Static assets
```

## Conventions

- **Backend models**: One SQLAlchemy model class per file in `backend/app/models/`, re-exported from `__init__.py`.
- **Backend services**: One service class per file in `backend/app/services/`, re-exported from `__init__.py`.
- **Backend controllers**: Each controller is a Flask Blueprint in its own file, registered in `app/__init__.py` with a URL prefix.
- **Error handling**: Controllers use a `@handle_errors` decorator for consistent JSON error responses. Custom exceptions extend `RealEstateAnalysisException`.
- **Validation**: All request validation uses Marshmallow schemas defined in `schemas.py`.
- **Frontend types**: All shared TypeScript types live in `src/types/index.ts`.
- **Frontend components**: One component per `.tsx` file in `src/components/`. Tests are co-located as `ComponentName.test.tsx`.
- **API layer**: All backend calls go through `src/services/api.ts` using Axios with React Query for caching.
- **Routing**: Frontend uses React Router v6 with routes defined in `App.tsx`. Backend API routes are prefixed with `/api`.
