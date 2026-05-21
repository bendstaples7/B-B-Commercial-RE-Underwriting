"""
Development launcher — starts Redis, Celery worker, and Flask in one command.

Usage:
    python dev.py

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
    # 2. Celery worker
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
    # 3. Migration check — refuse to start Flask if DB is behind head
    # ------------------------------------------------------------------
    print("  Checking database migrations...")
    migration_check = subprocess.run(
        [sys.executable, "-c",
         "import sys, os; sys.path.insert(0, '.'); "
         "from dotenv import load_dotenv; load_dotenv(); "
         "from alembic.config import Config; "
         "from alembic.script import ScriptDirectory; "
         "from alembic.runtime.migration import MigrationContext; "
         "import sqlalchemy as sa; "
         "cfg = Config(os.path.join(os.getcwd(), 'alembic_migrations', 'alembic.ini')); "
         "cfg.set_main_option('script_location', os.path.join(os.getcwd(), 'alembic_migrations')); "
         "script = ScriptDirectory.from_config(cfg); "
         "heads = {s.revision for s in script.get_revisions('heads')}; "
         "engine = sa.create_engine(os.environ.get('DATABASE_URL', 'postgresql://localhost/real_estate_analysis')); "
         "conn = engine.connect(); "
         "ctx = MigrationContext.configure(conn); "
         "current = set(ctx.get_current_heads()); "
         "conn.close(); "
         "sys.exit(0 if current == heads else 1)"
        ],
        cwd=BACKEND_DIR,
        env={**os.environ, "PYTHONPATH": BACKEND_DIR},
        capture_output=True,
        text=True,
    )
    if migration_check.returncode != 0:
        print("\n  ╔══════════════════════════════════════════════════════════╗")
        print("  ║  DATABASE MIGRATIONS PENDING — CANNOT START SERVER      ║")
        print("  ╠══════════════════════════════════════════════════════════╣")
        print("  ║  The database schema is behind the current codebase.    ║")
        print("  ║                                                          ║")
        print("  ║  Fix:  cd backend && flask db upgrade head               ║")
        print("  ║  Then re-run:  python dev.py                             ║")
        print("  ╚══════════════════════════════════════════════════════════╝\n")
        sys.exit(1)
    print("  Database migrations up to date ✓")

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
    main()
