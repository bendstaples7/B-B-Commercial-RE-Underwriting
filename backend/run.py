"""Application entry point."""
import os
import sys
from dotenv import load_dotenv

# Ensure we're running from the backend directory regardless of where
# the script was invoked from. This makes `python backend/run.py` from
# the project root work the same as `python run.py` from backend/.
backend_dir = os.path.dirname(os.path.abspath(__file__))

# Only change directory if we're not already in the backend directory
if os.getcwd() != backend_dir:
    os.chdir(backend_dir)

load_dotenv()

from app import create_app, db

app = create_app()

if __name__ == '__main__':
    # db.create_all() intentionally removed — Alembic migrations (run automatically
    # at startup in development via create_app) are the sole source of truth for
    # schema. Calling db.create_all() here would create tables before Alembic runs,
    # causing "relation already exists" errors and preventing migrations from applying.
    
    # Determine if we should use the reloader based on whether we changed directories
    # If we changed directories, disable the reloader to avoid path issues
    use_reloader = (os.getcwd() == backend_dir and 'backend' not in sys.argv[0])
    
    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=use_reloader)
