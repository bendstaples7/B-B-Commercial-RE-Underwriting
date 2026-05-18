"""Application entry point."""
import os
import socket

from app import create_app, db
from dotenv import load_dotenv

load_dotenv()


def _check_redis():
    """Warn if Redis is not reachable — Celery tasks will fail without it."""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    # Parse host/port from the URL (handles redis://host:port/db)
    try:
        from urllib.parse import urlparse
        parsed = urlparse(redis_url)
        host = parsed.hostname or "localhost"
        port = parsed.port or 6379
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            if s.connect_ex((host, port)) != 0:
                print(
                    f"\n  ⚠️  WARNING: Redis is not reachable at {host}:{port}.\n"
                    f"     Celery tasks (PDF parsing, AI extraction, HubSpot imports) will fail.\n"
                    f"     Run `python dev.py` from the project root to start everything automatically.\n"
                )
    except Exception:
        pass  # Don't crash startup over a connectivity check


def _warn_celery_not_running():
    """Warn that this script does not start the Celery worker."""
    print(
        "\n  ⚠️  NOTE: Running Flask directly via run.py does NOT start the Celery worker.\n"
        "     Background tasks (HubSpot imports, OM PDF processing, bulk lead rescoring)\n"
        "     will queue but never execute.\n"
        "     Use `python dev.py` from the project root to start everything at once.\n"
    )


app = create_app()

if __name__ == '__main__':
    _check_redis()
    _warn_celery_not_running()
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)
