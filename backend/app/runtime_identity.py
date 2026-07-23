"""Process identity for /api/health — detect stale Flask processes after code edits.

``build_id`` is unique per process start. ``source_stale`` becomes true when
loaded backend ``.py`` modules change after the process started.

Local restart strategy (pick one owner — never both):
- With Werkzeug reloader on (default ``run.py``): the reloader owns reloads;
  health never DETACHED-spawns a second tree.
- With ``FLASK_SKIP_RELOADER=1``: health may schedule a spawn+exit restart when
  ``allow_restart=True`` (loopback-only from the health routes).
"""

from __future__ import annotations

import hashlib
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_DIR.parent

_STARTED_AT = time.time()
_STARTED_AT_NS = time.time_ns()
_PID = os.getpid()
_BUILD_ID: str | None = None
_RESTART_SCHEDULED = False
_RESTART_LOCK = threading.Lock()


def _git_sha() -> str:
    """Best-effort short repo SHA. Never raises."""
    deploy_sha = _REPO_ROOT / "DEPLOY_SHA"
    try:
        if deploy_sha.is_file():
            sha = deploy_sha.read_text(encoding="utf-8").strip()
            if sha:
                return sha[:12]
    except OSError:
        pass

    git_head = _REPO_ROOT / ".git" / "HEAD"
    try:
        if git_head.is_file():
            head = git_head.read_text(encoding="utf-8").strip()
            if head.startswith("ref: "):
                ref_path = _REPO_ROOT / ".git" / head[5:]
                if ref_path.is_file():
                    sha = ref_path.read_text(encoding="utf-8").strip()
                    if sha:
                        return sha[:12]
            elif len(head) >= 12:
                return head[:12]
    except OSError:
        pass

    try:
        sha = (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=str(_REPO_ROOT),
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
        if sha:
            return sha[:12]
    except Exception:
        pass
    return "unknown"


def compute_source_fingerprint() -> str:
    """Stable hash of per-file nanosecond mtimes for loaded backend modules."""
    mtimes = _loaded_backend_mtimes()
    payload = "\n".join(
        f"{os.path.relpath(path, str(_BACKEND_DIR))}:{mtime_ns}"
        for path, mtime_ns in sorted(mtimes.items())
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _is_under_backend(path: str) -> bool:
    """True when *path* resolves inside the backend tree (not a sibling like backend-old)."""
    try:
        Path(path).resolve().relative_to(_BACKEND_DIR.resolve())
        return True
    except (OSError, ValueError):
        return False


def _loaded_backend_mtimes() -> dict[str, int]:
    """``path → st_mtime_ns`` for currently loaded backend ``.py`` modules."""
    out: dict[str, int] = {}
    for module in list(sys.modules.values()):
        file = getattr(module, "__file__", None)
        if not file or not file.endswith(".py"):
            continue
        if not _is_under_backend(file):
            continue
        try:
            out[file] = os.stat(file).st_mtime_ns
        except OSError:
            continue
    return out


def is_source_stale() -> bool:
    """True when any loaded backend ``.py`` was modified after process start."""
    for mtime_ns in _loaded_backend_mtimes().values():
        if mtime_ns > _STARTED_AT_NS:
            return True
    return False


def _reloader_owns_restarts() -> bool:
    """True when Werkzeug reloader is the active restart owner.

    The reloader child sets ``WERKZEUG_RUN_MAIN=true``. Spawning a DETACHED
    replacement from that process races the parent reloader and can dual-bind
    port 5000 on Windows.
    """
    return os.environ.get("WERKZEUG_RUN_MAIN") == "true"


def _auto_restart_enabled() -> bool:
    """Local/dev spawn-restart — never in production, pytest, or under reloader."""
    if os.environ.get("BB_DISABLE_AUTO_RESTART", "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        return False
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    if os.environ.get("FLASK_ENV", "development") == "production":
        return False
    if _reloader_owns_restarts():
        return False
    # Opt-in for spawn path (reloader-off local). Reloader path needs no flag.
    if os.environ.get("BB_ALLOW_AUTO_RESTART", "").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        # Default allow when reloader is explicitly skipped (common agent/debug).
        if os.environ.get("FLASK_SKIP_RELOADER", "").strip().lower() not in (
            "1",
            "true",
            "yes",
        ):
            return False
    return True


def _perform_restart() -> None:
    """Spawn a replacement ``run.py`` then exit so the listen port is released."""
    run_py = _BACKEND_DIR / "run.py"
    cmd = [sys.executable, str(run_py)]
    env = os.environ.copy()
    # Child must not start another reloader tree beside a dying parent.
    env["FLASK_SKIP_RELOADER"] = "1"
    kwargs: dict = {
        "cwd": str(_BACKEND_DIR),
        "env": env,
        "close_fds": True,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        )
        # Keep a console so port-guard / startup failures are visible locally.
    else:
        kwargs["start_new_session"] = True

    logger.warning(
        "source_stale: spawning replacement Flask process then exiting (pid=%s)",
        _PID,
    )
    subprocess.Popen(cmd, **kwargs)
    time.sleep(0.35)
    os._exit(0)


def schedule_local_dev_restart(*, reason: str = "source_stale") -> bool:
    """Schedule one automatic restart when local sources are stale.

    Returns True when a restart is already scheduled or newly scheduled.
    """
    global _RESTART_SCHEDULED
    if not _auto_restart_enabled():
        return False
    with _RESTART_LOCK:
        if _RESTART_SCHEDULED:
            return True
        _RESTART_SCHEDULED = True

    logger.warning("Scheduling local Flask restart (%s)", reason)

    def _runner() -> None:
        time.sleep(0.4)
        try:
            _perform_restart()
        except Exception:
            logger.exception("Automatic Flask restart failed")
            with _RESTART_LOCK:
                global _RESTART_SCHEDULED
                _RESTART_SCHEDULED = False

    threading.Thread(
        target=_runner,
        name="bb-local-dev-restart",
        daemon=True,
    ).start()
    return True


def init_runtime_identity() -> None:
    """Capture build_id once at process start (call from create_app)."""
    global _BUILD_ID
    if _BUILD_ID is not None:
        return
    started = datetime.fromtimestamp(_STARTED_AT, tz=timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    _BUILD_ID = f"{_git_sha()}-{started}-pid{_PID}"


def runtime_identity_exposed() -> bool:
    """Only expose process identity outside production."""
    return os.environ.get("FLASK_ENV", "development") != "production"


def get_runtime_identity(*, allow_restart: bool = False) -> dict:
    """Payload fields for the health endpoints (empty in production).

    ``allow_restart`` must be True only for trusted callers (e.g. loopback
    health probes). Public LAN hits must not kill the process.
    """
    if not runtime_identity_exposed():
        return {}
    if _BUILD_ID is None:
        init_runtime_identity()
    assert _BUILD_ID is not None
    stale = is_source_stale()
    restart_scheduled = False
    if stale and allow_restart:
        restart_scheduled = schedule_local_dev_restart(reason="source_stale")
    return {
        "build_id": _BUILD_ID,
        "pid": _PID,
        "started_at": datetime.fromtimestamp(_STARTED_AT, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "source_stale": stale,
        "restart_scheduled": restart_scheduled,
    }
