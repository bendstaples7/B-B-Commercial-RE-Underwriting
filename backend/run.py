"""Application entry point."""
import os
from dotenv import load_dotenv

# Ensure we're running from the backend directory regardless of where
# the script was invoked from. This makes `python backend/run.py` from
# the project root work the same as `python run.py` from backend/.
backend_dir = os.path.dirname(os.path.abspath(__file__))

# Track whether we changed directories — if we did, disable the reloader
# to avoid Flask's stat-based reloader trying to find the script at the
# original (now-wrong) path.
_changed_dir = os.getcwd() != backend_dir
if _changed_dir:
    os.chdir(backend_dir)

load_dotenv()

from app import create_app, db

app = create_app()

if __name__ == '__main__':
    # db.create_all() intentionally removed — Alembic migrations (run automatically
    # at startup in development via create_app) are the sole source of truth for
    # schema. Calling db.create_all() here would create tables before Alembic runs,
    # causing "relation already exists" errors and preventing migrations from applying.
    
    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=not _changed_dir)
