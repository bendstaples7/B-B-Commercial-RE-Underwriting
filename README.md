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

4. Initialize database:
```bash
python run.py
```

The backend will run on http://localhost:5000

### Frontend Setup

1. Install dependencies:
```bash
cd frontend
npm install
```

2. Configure environment variables:
```bash
copy .env.example .env
# Edit .env with your configuration
```

3. Start development server:
```bash
npm run dev
```

The frontend will run on http://localhost:3000

### Database Setup

1. Create PostgreSQL database:
```sql
CREATE DATABASE real_estate_analysis;
```

2. Run migrations (tables will be created automatically on first run)

### Redis Setup

Ensure Redis is running on localhost:6379 or configure REDIS_URL in .env

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
