"""
Development launcher — starts Redis, Celery worker, and Flask in one command.

Usage:
    python dev.py          # start the full dev environment
    python dev.py check    # run pre-flight checks only (no servers started)

Starts:
    1. Redis server (if not already running)
    2. Celery worker (background)
    3. Flask dev server (foreground)

All processes are cleaned up on Ctrl+C.
"""

import os
import signal
import subprocess
import sys
import time
import socket
import atexit

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BACKEND_DIR = os.path.join(os.path.dirname(__file__), "backend")
REDIS_PORT = 6379
FLASK_PORT = 5000


def _is_local_database_url(url: str) -> bool:
    """True when DATABASE_URL points at a local dev database (safe to auto-migrate)."""
    lower = url.lower()
    return (
        'localhost' in lower
        or '127.0.0.1' in lower
        or lower.startswith('postgresql:///@')
        or 'host=/var/run/postgresql' in lower
    )

# Processes we start (so we can clean them up)
_processes: list[subprocess.Popen] = []


def _cleanup():
    """Terminate all child processes on exit."""
    for proc in _processes:
        if proc.poll() is None:  # still running
            print(f"  Stopping PID {proc.pid}...")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


atexit.register(_cleanup)


def _handle_sigint(sig, frame):
    print("\n\nShutting down dev environment...")
    sys.exit(0)


signal.signal(signal.SIGINT, _handle_sigint)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_port_open(host: str, port: int) -> bool:
    """Return True if something is already listening on host:port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex((host, port)) == 0


def _start(label: str, cmd: list[str], cwd: str = None, env: dict = None) -> subprocess.Popen:
    """Start a subprocess and register it for cleanup."""
    merged_env = {**os.environ, **(env or {})}
    print(f"  Starting {label}...")
    proc = subprocess.Popen(
        cmd,
        cwd=cwd or BACKEND_DIR,
        env=merged_env,
        # Let output flow to the terminal
        stdout=None,
        stderr=None,
    )
    _processes.append(proc)
    return proc


# ---------------------------------------------------------------------------
# Production data gate — runs before pre-flight checks
# ---------------------------------------------------------------------------

def ensure_local_prod_data() -> bool:
    """Auto-restore production DB dump when local leads are missing."""
    root = os.path.dirname(__file__)
    scripts = os.path.join(root, "scripts")

    if sys.platform == "win32":
        script = os.path.join(scripts, "ensure-local-prod-data.ps1")
        if not os.path.isfile(script):
            return True
        cmd = [
            "powershell", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", script,
        ]
    else:
        script = os.path.join(scripts, "ensure-local-prod-data.sh")
        if not os.path.isfile(script):
            return True
        cmd = ["bash", script]

    print("\n  Checking local production data...")
    print("  " + "-" * 50)
    result = subprocess.run(cmd, cwd=root)
    print("  " + "-" * 50)
    if result.returncode != 0:
        print("  Production data restore failed — cannot start dev environment.\n")
        return False
    return True


# ---------------------------------------------------------------------------
# Pre-flight checks (also called by `main` before starting Flask)
# ---------------------------------------------------------------------------

def run_checks() -> bool:
    """Run all pre-flight checks. Returns True if everything passes.

    Checks:
      1. No duplicate Alembic revision IDs in migration files
      2. Migration chain has exactly one head (no branches)
      3. Frontend package.json dependencies are installed (node_modules exists)

    Run standalone with:  python dev.py check
    """
    import glob
    import re

    frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
    migrations_dir = os.path.join(BACKEND_DIR, "alembic_migrations")
    passed = True

    print("\n  Running pre-flight checks...")
    print("  " + "-" * 50)

    # ------------------------------------------------------------------
    # Check 1: No duplicate revision IDs
    # ------------------------------------------------------------------
    revision_pattern = re.compile(r"^revision\s*=\s*'([^']+)'", re.MULTILINE)
    seen: dict[str, str] = {}
    duplicates: list[str] = []

    for filepath in glob.glob(os.path.join(migrations_dir, "versions", "*.py")):
        try:
            with open(filepath, encoding="utf-8") as f:
                content = f.read()
        except (OSError, UnicodeDecodeError) as exc:
            duplicates.append(f"    WARNING: could not read '{os.path.basename(filepath)}': {exc}")
            continue
        match = revision_pattern.search(content)
        if match:
            rev = match.group(1)
            filename = os.path.basename(filepath)
            if rev in seen:
                duplicates.append(f"    '{rev}' in '{seen[rev]}' AND '{filename}'")
            else:
                seen[rev] = filename

    if duplicates:
        print("  ✗ Duplicate Alembic revision IDs:")
        for d in duplicates:
            print(d)
        print("    Fix: rename the duplicate revision ID in one of the listed files.")
        passed = False
    else:
        print(f"  ✓ Migration revision IDs are unique ({len(seen)} migrations)")

    # ------------------------------------------------------------------
    # Check 2: Single migration head
    # ------------------------------------------------------------------
    try:
        sys.path.insert(0, BACKEND_DIR)
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config()
        cfg.set_main_option("script_location", migrations_dir)
        script = ScriptDirectory.from_config(cfg)
        heads = script.get_heads()

        if len(heads) != 1:
            print(f"  ✗ Migration chain has {len(heads)} heads: {heads}")
            print("    Fix: flask db merge -m 'merge branches' " + " ".join(heads))
            passed = False
        else:
            print(f"  ✓ Migration chain has a single head ({heads[0]})")
    except Exception as e:
        print(f"  ✗ Could not check migration heads: {e}")
        passed = False

    # ------------------------------------------------------------------
    # Check 3: Database is at migration head
    # ------------------------------------------------------------------
    try:
        import sqlalchemy as sa
        from alembic.runtime.migration import MigrationContext
        sys.path.insert(0, BACKEND_DIR)
        from env_loader import load_project_env
        load_project_env()

        db_url = os.environ.get("DATABASE_URL", "postgresql://localhost/real_estate_analysis")
        engine = sa.create_engine(db_url)
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            current_heads = set(ctx.get_current_heads())

        # Re-use the already-loaded script if available
        try:
            expected_heads = set(script.get_heads())
        except NameError:
            from alembic.config import Config as _Config
            from alembic.script import ScriptDirectory as _SD
            _cfg = _Config()
            _cfg.set_main_option("script_location", migrations_dir)
            expected_heads = set(_SD.from_config(_cfg).get_heads())

        if current_heads == expected_heads:
            print(f"  ✓ Database is at migration head ({', '.join(expected_heads)})")
        elif not _is_local_database_url(db_url):
            print("  ✗ Database schema is out of date but DATABASE_URL is not local")
            print(f"    Current : {current_heads or '(none — fresh DB)'}")
            print(f"    Expected: {expected_heads}")
            print("    Fix: run `cd backend && flask db upgrade head` against your local database")
            passed = False
        else:
            print("  ⚙ Database schema is out of date — running flask db upgrade head...")
            print(f"    Current : {current_heads or '(none — fresh DB)'}")
            print(f"    Expected: {expected_heads}")
            try:
                upgrade_env = {
                    **os.environ,
                    "FLASK_APP": "app",
                    "FLASK_ENV": "development",
                    "PYTHONIOENCODING": "utf-8",
                }
                subprocess.run(
                    [sys.executable, "-m", "flask", "db", "upgrade", "head"],
                    cwd=BACKEND_DIR,
                    env=upgrade_env,
                    check=True,
                )
                with engine.connect() as conn:
                    ctx = MigrationContext.configure(conn)
                    current_heads = set(ctx.get_current_heads())
                if current_heads == expected_heads:
                    print(f"  ✓ Database upgraded to migration head ({', '.join(expected_heads)})")
                else:
                    print(f"  ✗ Upgrade did not reach head (now at {current_heads})")
                    passed = False
            except subprocess.CalledProcessError as upgrade_err:
                print(f"  ✗ flask db upgrade failed (exit {upgrade_err.returncode})")
                passed = False
            except Exception as upgrade_err:
                print(f"  ✗ flask db upgrade failed: {upgrade_err}")
                passed = False
    except Exception as e:
        print(f"  ✗ Could not verify database migration head: {e}")
        passed = False

    # ------------------------------------------------------------------
    # Check 3b: Local database has production lead data
    # ------------------------------------------------------------------
    try:
        import sqlalchemy as sa
        sys.path.insert(0, BACKEND_DIR)
        from env_loader import load_project_env
        load_project_env()

        db_url = os.environ.get("DATABASE_URL", "postgresql://localhost/real_estate_analysis")
        engine = sa.create_engine(db_url)
        with engine.connect() as conn:
            lead_count = conn.execute(sa.text("SELECT count(*) FROM leads")).scalar() or 0

        if lead_count < 1000:
            print(f"  ✗ Local database has only {lead_count} leads (expected 1,000+)")
            print("     Auto-restore did not populate lead data — check ensure-local-prod-data logs.")
            passed = False
        else:
            print(f"  ✓ Local database has {lead_count:,} leads")
    except Exception as e:
        print(f"  ⚠️  Could not check lead count: {e}")

    # ------------------------------------------------------------------
    # Check 4: Frontend node_modules installed
    # ------------------------------------------------------------------
    node_modules = os.path.join(frontend_dir, "node_modules")
    if not os.path.isdir(node_modules):
        print("  ✗ frontend/node_modules not found — run: cd frontend && npm install")
        passed = False
    else:
        print("  ✓ frontend/node_modules present")

    print("  " + "-" * 50)
    if passed:
        print("  All checks passed ✓\n")
    else:
        print("  One or more checks failed. Fix the issues above before starting.\n")

    return passed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  B&B Real Estate Analyzer — Dev Environment")
    print("=" * 60)

    # ------------------------------------------------------------------
    # 1. Redis
    # ------------------------------------------------------------------
    if _is_port_open("127.0.0.1", REDIS_PORT):
        print(f"  Redis already running on port {REDIS_PORT} ✓")
    else:
        print(f"  Redis not detected on port {REDIS_PORT}, starting...")
        # Try redis-server (works if Redis is on PATH — e.g. via Memurai,
        # WSL, or a native Windows Redis install)
        # Try redis-server on PATH first, then fall back to the portable install location
        redis_exe = "redis-server"
        portable_path = os.path.join(os.path.expanduser("~"), "redis", "redis-server.exe")
        if not any(
            os.path.isfile(os.path.join(p, "redis-server.exe"))
            for p in os.environ.get("PATH", "").split(os.pathsep)
        ) and os.path.isfile(portable_path):
            redis_exe = portable_path

        try:
            redis_proc = _start("Redis", [redis_exe, "--port", str(REDIS_PORT)])
            time.sleep(1.5)  # give it a moment to bind
            if not _is_port_open("127.0.0.1", REDIS_PORT):
                print("\n  ⚠️  Redis failed to start.")
                print("     Make sure Redis (or Memurai) is installed and on your PATH.")
                print("     Download: https://github.com/tporadowski/redis/releases")
                print("     Or install Memurai: https://www.memurai.com/")
                print("\n  Continuing without Redis — Celery tasks will fail.\n")
            else:
                print(f"  Redis started on port {REDIS_PORT} ✓")
        except FileNotFoundError:
            print("\n  ⚠️  redis-server not found on PATH.")
            print("     Install Redis for Windows: https://github.com/tporadowski/redis/releases")
            print("     Or install Memurai (Redis-compatible): https://www.memurai.com/")
            print("\n  Continuing without Redis — Celery tasks will fail.\n")

    # ------------------------------------------------------------------
    # 2. Production data + pre-flight checks (includes DB migration)
    # ------------------------------------------------------------------
    if not ensure_local_prod_data():
        sys.exit(1)

    if not run_checks():
        sys.exit(1)

    # ------------------------------------------------------------------
    # 3. Celery worker (after schema is at migration head)
    # ------------------------------------------------------------------
    celery_env = {"PYTHONPATH": BACKEND_DIR, "CELERY_WORKER_RUNNING": "1"}
    _start(
        "Celery worker",
        [sys.executable, "-m", "celery", "-A", "celery_worker", "worker", "--loglevel=info", "--pool=threads", "--concurrency=2"],
        cwd=BACKEND_DIR,
        env=celery_env,
    )
    # Option 2: also start Celery Beat for scheduled tasks (nightly signal extraction)
    _start(
        "Celery beat",
        [sys.executable, "-m", "celery", "-A", "celery_worker", "beat", "--loglevel=info"],
        cwd=BACKEND_DIR,
        env=celery_env,
    )
    time.sleep(1)  # let Celery connect to Redis before Flask starts

    # ------------------------------------------------------------------
    # 4. Flask dev server (foreground — blocks until Ctrl+C)
    # ------------------------------------------------------------------
    print(f"\n  Flask starting on http://localhost:{FLASK_PORT}")
    print("  Press Ctrl+C to stop all services.\n")
    print("=" * 60 + "\n")

    flask_proc = subprocess.run(
        [sys.executable, "run.py"],
        cwd=BACKEND_DIR,
        env={**os.environ, "PYTHONPATH": BACKEND_DIR},
    )


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "check":
        sys.exit(0 if run_checks() else 1)
    else:
        main()
