"""
Development launcher — starts Redis, Celery worker, and Flask in one command.

Usage:
    python dev.py          # start the full dev environment
    python dev.py check    # run pre-flight checks only (no servers started)

Starts:
    1. Redis server (if not already running)
    2. Celery worker (background)
    3. Flask dev server (foreground)

All processes are cleaned up on Ctrl+C. Prior children from a previous
``dev.py`` run (tracked via ``.dev/pids/*.pid``) are stopped first so a
second launch cannot leave stale Flask listeners on port 5000.
"""

import os
import re
import signal
import subprocess
import sys
import time
import socket
import atexit

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
PID_DIR = os.path.join(ROOT_DIR, ".dev", "pids")
REDIS_PORT = 6379
FLASK_PORT = 5000

# Ensure backend/ is importable for port_guard (shared with run.py).
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


def _is_local_database_url(url: str) -> bool:
    """True when DATABASE_URL points at a local dev database (safe to auto-migrate)."""
    lower = url.lower()
    if 'localhost' in lower or '127.0.0.1' in lower:
        return True
    if 'host=/var/run/postgresql' in lower:
        return True
    # Hostless local socket URL: postgresql:///dbname
    return re.match(r'^postgresql:///[^@]', lower) is not None

# Processes we start (so we can clean them up)
_processes: list[subprocess.Popen] = []
_pid_files_written: list[str] = []


def _pid_path(name: str) -> str:
    return os.path.join(PID_DIR, f"{name}.pid")


def _write_pid(name: str, pid: int) -> None:
    os.makedirs(PID_DIR, exist_ok=True)
    path = _pid_path(name)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(str(pid))
    _pid_files_written.append(path)


def _read_pid(name: str) -> int | None:
    path = _pid_path(name)
    if not os.path.isfile(path):
        return None
    try:
        raw = open(path, encoding="utf-8").read().strip()
        return int(raw) if raw else None
    except (OSError, ValueError):
        return None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            # /FO CSV /NH yields one quoted row per process; match the exact
            # PID column so PID 123 never matches 1236.
            out = subprocess.check_output(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                text=True,
                errors="replace",
                stderr=subprocess.DEVNULL,
            )
            return f'"{pid}"' in out
        except (OSError, subprocess.CalledProcessError):
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _cmdline_for_pid(pid: int) -> str:
    """Best-effort process command line (empty string if unavailable)."""
    try:
        from port_guard import describe_pid

        cmdline = describe_pid(pid) or ""
        if cmdline:
            return cmdline
    except Exception:
        pass
    try:
        return subprocess.check_output(
            ["ps", "-p", str(pid), "-o", "command="],
            text=True,
            errors="replace",
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _cmdline_matches(pid: int, expect_all: tuple[str, ...]) -> bool:
    """True when the process cmdline contains every expected token (case-insensitive)."""
    if not expect_all:
        return True
    cmd = _cmdline_for_pid(pid).lower()
    if not cmd:
        # No cmdline visibility — refuse to kill rather than risk a wrong target.
        return False
    return all(tok.lower() in cmd for tok in expect_all)


def _stop_pid(
    pid: int,
    label: str = "process",
    *,
    expect_any: tuple[str, ...] = (),
) -> None:
    if not _pid_alive(pid):
        return
    # Guard against stale pidfiles / recycled PIDs: only kill when the running
    # process looks like what we expect (e.g. redis-server, celery, run.py).
    if not _cmdline_matches(pid, expect_any):
        print(
            f"  Skipping {label} (PID {pid}): running process does not match "
            f"{expect_any!r} — likely a recycled PID."
        )
        return
    print(f"  Stopping prior {label} (PID {pid})...")
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/F", "/T"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return
        deadline = time.time() + 5
        while time.time() < deadline and _pid_alive(pid):
            time.sleep(0.2)
        if _pid_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass


def _clear_pid_file(name: str) -> None:
    path = _pid_path(name)
    try:
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


# Expected cmdline tokens per recorded child (ALL must match), so a stale/recycled
# PID from a previous run is never force-killed unless it still looks like ours.
_EXPECT_TOKENS: dict[str, tuple[str, ...]] = {
    "celery": ("celery", "worker"),
    "celery-beat": ("celery", "beat"),
    "flask": ("run.py",),
    "redis": ("redis-server",),
}
# A Flask-port listener we did not record must look like our server before we
# kill it (avoid nuking an unrelated process that grabbed 5000).
_FLASK_LISTENER_TOKENS: tuple[str, ...] = ("run.py", "flask")


def _stop_prior_dev_children() -> None:
    """Stop processes recorded by a previous ``dev.py`` run and free Flask port."""
    for name in ("celery", "celery-beat", "flask", "redis"):
        pid = _read_pid(name)
        if pid is not None:
            _stop_pid(pid, label=name, expect_any=_EXPECT_TOKENS.get(name, ()))
            _clear_pid_file(name)

    # Also kill anything still listening on the Flask port (orphans from
    # ``python run.py`` without going through this launcher) — but only if it
    # matches our server signature.
    try:
        from port_guard import list_listening_pids
    except ImportError:
        return

    listeners = list_listening_pids(FLASK_PORT)
    for pid in listeners:
        _stop_pid(
            pid,
            label=f"port-{FLASK_PORT} listener",
            expect_any=_FLASK_LISTENER_TOKENS,
        )
    # Poll until the port is released (Windows can lag on handle release),
    # rather than a fixed sleep that may be too short.
    if listeners:
        deadline = time.time() + 5
        while time.time() < deadline and list_listening_pids(FLASK_PORT):
            time.sleep(0.25)


def _cleanup():
    """Terminate all child processes on exit."""
    for proc in _processes:
        if proc.poll() is None:  # still running
            print(f"  Stopping PID {proc.pid}...")
            if sys.platform == "win32":
                # Tree-kill so grandchild workers (celery pool, flask) don't orphan.
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/F", "/T"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
            else:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
    for path in _pid_files_written:
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError:
            pass


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


def _start(
    label: str,
    cmd: list[str],
    cwd: str = None,
    env: dict = None,
    *,
    pid_name: str | None = None,
) -> subprocess.Popen:
    """Start a subprocess and register it for cleanup."""
    merged_env = {**os.environ, **(env or {})}
    print(f"  Starting {label}...")
    proc = subprocess.Popen(
        cmd,
        cwd=cwd or BACKEND_DIR,
        env=merged_env,
        stdout=None,
        stderr=None,
    )
    _processes.append(proc)
    if pid_name:
        _write_pid(pid_name, proc.pid)
    return proc


# ---------------------------------------------------------------------------
# Production data gate — runs before pre-flight checks
# ---------------------------------------------------------------------------

def ensure_local_prod_data() -> bool:
    """Auto-restore production DB dump when local leads are missing."""
    root = ROOT_DIR
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
    # 0. Stop prior children / free Flask port (before Redis / Celery)
    # ------------------------------------------------------------------
    print("\n  Releasing prior dev processes (if any)...")
    _stop_prior_dev_children()

    # ------------------------------------------------------------------
    # 1. Redis
    # ------------------------------------------------------------------
    if _is_port_open("127.0.0.1", REDIS_PORT):
        print(f"  Redis already running on port {REDIS_PORT} ✓")
    else:
        print(f"  Redis not detected on port {REDIS_PORT}, starting...")
        redis_exe = "redis-server"
        portable_path = os.path.join(os.path.expanduser("~"), "redis", "redis-server.exe")
        if not any(
            os.path.isfile(os.path.join(p, "redis-server.exe"))
            for p in os.environ.get("PATH", "").split(os.pathsep)
        ) and os.path.isfile(portable_path):
            redis_exe = portable_path

        try:
            _start("Redis", [redis_exe, "--port", str(REDIS_PORT)], pid_name="redis")
            time.sleep(1.5)
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
        pid_name="celery",
    )
    _start(
        "Celery beat",
        [sys.executable, "-m", "celery", "-A", "celery_worker", "beat", "--loglevel=info"],
        cwd=BACKEND_DIR,
        env=celery_env,
        pid_name="celery-beat",
    )
    time.sleep(1)

    # ------------------------------------------------------------------
    # 4. Flask dev server (foreground — blocks until Ctrl+C)
    # ------------------------------------------------------------------
    from port_guard import assert_port_free
    assert_port_free(FLASK_PORT)

    print(f"\n  Flask starting on http://localhost:{FLASK_PORT}")
    print("  Press Ctrl+C to stop all services.\n")
    print("=" * 60 + "\n")

    flask_proc = subprocess.Popen(
        [sys.executable, "run.py"],
        cwd=BACKEND_DIR,
        env={**os.environ, "PYTHONPATH": BACKEND_DIR},
    )
    _processes.append(flask_proc)
    _write_pid("flask", flask_proc.pid)
    try:
        flask_proc.wait()
    except KeyboardInterrupt:
        pass
    sys.exit(flask_proc.returncode or 0)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "check":
        sys.exit(0 if run_checks() else 1)
    else:
        main()
