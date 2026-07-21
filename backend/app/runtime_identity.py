"""Process identity for /api/health — detect stale Flask processes after code edits.

``build_id`` is unique per process start. ``source_stale`` becomes true when
Python sources under ``backend/app`` (plus entrypoints) change after the
process started — typical with ``use_reloader=False`` during local development.
"""

from __future__ import annotations

import hashlib
import os
import time
from datetime import datetime, timezone
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_DIR.parent

_STARTED_AT = time.time()
_STARTED_AT_NS = time.time_ns()
_PID = os.getpid()
_BUILD_ID: str | None = None


def _git_sha() -> str:
    """Best-effort short repo SHA. Never raises."""
    # Prefer DEPLOY_SHA (prod), then local .git — mirror resolve_deploy_sha without
    # importing routes (avoids circular import via create_app → runtime_identity).
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
        import subprocess

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
    import sys

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
    """True when any loaded backend ``.py`` was modified after process start.

    Uses nanosecond mtimes so same-second edits are not missed. Lazily imported
    modules that predate process start do not trip the banner.
    """
    for mtime_ns in _loaded_backend_mtimes().values():
        if mtime_ns > _STARTED_AT_NS:
            return True
    return False


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
    """Only expose process identity outside production.

    ``source_stale`` is a local-dev aid (``run.py`` runs with
    ``use_reloader=False``); production is managed by systemd/gunicorn and must
    not leak pid / build_id / restart timing to unauthenticated callers.
    """
    return os.environ.get("FLASK_ENV", "development") != "production"


def get_runtime_identity() -> dict:
    """Payload fields for the health endpoints (empty in production)."""
    if not runtime_identity_exposed():
        return {}
    if _BUILD_ID is None:
        init_runtime_identity()
    assert _BUILD_ID is not None
    return {
        "build_id": _BUILD_ID,
        "pid": _PID,
        "started_at": datetime.fromtimestamp(_STARTED_AT, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "source_stale": is_source_stale(),
    }
