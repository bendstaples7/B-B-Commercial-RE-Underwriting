"""Host memory / Celery RSS helpers for health and ops probes."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def read_meminfo(path: str | Path = "/proc/meminfo") -> dict[str, int]:
    """Parse /proc/meminfo into {key: kib} (Linux). Empty dict if unavailable."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return {}
    out: dict[str, int] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, rest = line.split(":", 1)
        parts = rest.strip().split()
        if not parts:
            continue
        try:
            out[key] = int(parts[0])
        except ValueError:
            continue
    return out


def host_memory_snapshot(meminfo: dict[str, int] | None = None) -> dict[str, Any]:
    """Return available/swap metrics in MiB plus swap-used percent."""
    info = meminfo if meminfo is not None else read_meminfo()
    if not info:
        return {
            "available": False,
            "reason": "meminfo_unavailable",
        }

    def _mib(key: str) -> float:
        return round(info.get(key, 0) / 1024.0, 1)

    mem_total = _mib("MemTotal")
    mem_available = _mib("MemAvailable")
    swap_total = _mib("SwapTotal")
    swap_free = _mib("SwapFree")
    swap_used = max(swap_total - swap_free, 0.0)
    swap_used_pct = (
        round((swap_used / swap_total) * 100.0, 1) if swap_total > 0 else 0.0
    )
    return {
        "available": True,
        "mem_total_mib": mem_total,
        "mem_available_mib": mem_available,
        "swap_total_mib": swap_total,
        "swap_used_mib": swap_used,
        "swap_used_pct": swap_used_pct,
    }


def _read_rss_kib(pid: int) -> int | None:
    try:
        status = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
    except OSError:
        return None
    for line in status.splitlines():
        if line.startswith("VmRSS:"):
            parts = line.split()
            try:
                return int(parts[1])
            except (IndexError, ValueError):
                return None
    return None


def _is_celery_worker_cmdline(text: str) -> bool:
    """True for our prefork worker; false for beat and unrelated processes."""
    lower = text.lower()
    if "beat" in lower:
        return False
    if "celery_worker" not in text and "-a celery_worker" not in lower:
        return False
    # Prefer explicit worker argv; allow celery_worker.celery without the word
    # "worker" only when the module path is present (systemd ExecStart shape).
    if " worker" in lower or "celery_worker.celery" in text:
        return True
    return False


def celery_child_rss_mib() -> dict[str, Any]:
    """Best-effort max RSS (MiB) among celery worker processes."""
    proc = Path("/proc")
    if not proc.is_dir():
        return {"available": False, "reason": "proc_unavailable"}

    max_rss_kib = 0
    matched = 0
    try:
        pids = [p.name for p in proc.iterdir() if p.name.isdigit()]
    except OSError:
        return {"available": False, "reason": "proc_list_failed"}

    for pid_s in pids:
        try:
            cmdline = Path(f"/proc/{pid_s}/cmdline").read_bytes()
        except OSError:
            continue
        text = cmdline.replace(b"\x00", b" ").decode("utf-8", errors="ignore")
        if "celery" not in text.lower():
            continue
        if not _is_celery_worker_cmdline(text):
            continue
        rss = _read_rss_kib(int(pid_s))
        if rss is None:
            continue
        matched += 1
        if rss > max_rss_kib:
            max_rss_kib = rss

    if matched == 0:
        return {"available": False, "reason": "no_celery_worker_rss"}

    return {
        "available": True,
        "celery_rss_mib": round(max_rss_kib / 1024.0, 1),
        "matched_processes": matched,
    }


def evaluate_host_memory_health(
    *,
    min_available_mib: float | None = None,
    max_swap_used_pct: float | None = None,
    max_celery_rss_mib: float | None = None,
    host: dict[str, Any] | None = None,
    celery: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a health-check fragment for memory pressure.

    Returns ok=False when thresholds are exceeded, but callers should treat
    this as a **WARN** (not HTTP 503) so Deploy/ops canaries do not flap on a
    small VPS under normal Celery load.

    Env overrides (optional):
      HEALTH_MEM_MIN_AVAILABLE_MIB (default 100)
      HEALTH_SWAP_MAX_USED_PCT (default 90)
      HEALTH_CELERY_MAX_RSS_MIB (default 700)

    Pass *host* / *celery* snapshots in tests to avoid reading /proc.
    """
    if min_available_mib is None:
        min_available_mib = float(os.environ.get("HEALTH_MEM_MIN_AVAILABLE_MIB", "100"))
    if max_swap_used_pct is None:
        max_swap_used_pct = float(os.environ.get("HEALTH_SWAP_MAX_USED_PCT", "90"))
    if max_celery_rss_mib is None:
        max_celery_rss_mib = float(os.environ.get("HEALTH_CELERY_MAX_RSS_MIB", "700"))

    host = host if host is not None else host_memory_snapshot()
    celery = celery if celery is not None else celery_child_rss_mib()
    failures: list[str] = []

    if host.get("available"):
        if host["mem_available_mib"] < min_available_mib:
            failures.append(
                f"MemAvailable {host['mem_available_mib']}MiB "
                f"< {min_available_mib}MiB"
            )
        if host["swap_total_mib"] > 0 and host["swap_used_pct"] > max_swap_used_pct:
            failures.append(
                f"swap used {host['swap_used_pct']}% > {max_swap_used_pct}%"
            )
    if celery.get("available") and celery["celery_rss_mib"] > max_celery_rss_mib:
        failures.append(
            f"Celery RSS {celery['celery_rss_mib']}MiB > {max_celery_rss_mib}MiB"
        )

    ok = not failures
    summary_parts = []
    if host.get("available"):
        summary_parts.append(
            f"MemAvailable={host['mem_available_mib']}MiB "
            f"swap={host['swap_used_pct']}%"
        )
    if celery.get("available"):
        summary_parts.append(f"celery_rss={celery['celery_rss_mib']}MiB")

    if ok:
        detail = "ok (" + ", ".join(summary_parts) + ")" if summary_parts else "ok"
    else:
        detail = "WARN: " + "; ".join(failures)

    return {
        "ok": ok,
        "detail": detail,
        "host": host,
        "celery": celery,
        "failures": failures,
    }
