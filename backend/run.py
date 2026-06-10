"""Application entry point."""
import os
import socket
import glob
import re

from app import create_app, db
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


def _check_migration_revision_uniqueness():
    """Fail fast if any two migration files share the same revision ID.

    Duplicate revision IDs cause Alembic to emit warnings and produce a
    branched graph, which then causes _assert_single_migration_head to
    abort startup with a cryptic error.  This check surfaces the problem
    immediately with the exact filenames involved.
    """
    migrations_dir = os.path.join(backend_dir, "alembic_migrations", "versions")
    revision_pattern = re.compile(r"^revision\s*=\s*'([^']+)'", re.MULTILINE)
    seen: dict[str, str] = {}
    duplicates: list[str] = []

    for filepath in glob.glob(os.path.join(migrations_dir, "*.py")):
        try:
            with open(filepath, encoding='utf-8') as f:
                content = f.read()
        except (OSError, UnicodeDecodeError) as exc:
            print(f"  WARNING: Could not read migration file '{os.path.basename(filepath)}': {exc} — skipping")
            continue
        match = revision_pattern.search(content)
        if match:
            rev = match.group(1)
            filename = os.path.basename(filepath)
            if rev in seen:
                duplicates.append(f"  '{rev}' in '{seen[rev]}' AND '{filename}'")
            else:
                seen[rev] = filename

    if duplicates:
        lines = ["", "", "DUPLICATE MIGRATION REVISION IDs — SERVER WILL NOT START", ""]
        for d in duplicates:
            lines.append(d)
        lines += [
            "",
            "Fix: rename the duplicate revision ID in one of the listed files,",
            "then create a merge migration:",
            "  flask db merge -m 'merge branches' <rev1> <rev2>",
            "",
        ]
        raise SystemExit("\n".join(lines))


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


_check_migration_revision_uniqueness()
app = create_app()

if __name__ == '__main__':
    _check_redis()
    _warn_celery_not_running()
    with app.app_context():
        db.create_all()
    app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)