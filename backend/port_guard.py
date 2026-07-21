"""Fail-fast helpers for local Flask port occupancy.

Windows allows multiple listeners on the same port when SO_REUSEADDR is set
(Werkzeug does this), so a naive bind() check is not enough — inspect the OS
listener table and refuse to start when foreign PIDs already own the port.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Iterable


class PortProbeError(RuntimeError):
    """Raised when the OS listener table could not be inspected.

    Callers that must fail-closed (``assert_port_free``) treat this as fatal,
    since an unknown port state on Windows can hide a stale SO_REUSEADDR
    co-listener — the exact bug this module guards against.
    """


def _probe_listening_pids(port: int) -> list[int]:
    """Return listening PIDs for ``port`` or raise ``PortProbeError``."""
    if port <= 0 or port > 65535:
        raise ValueError(f"invalid port: {port}")

    if sys.platform == "win32":
        return _list_listening_pids_windows(port)
    return _list_listening_pids_posix(port)


def list_listening_pids(port: int) -> list[int]:
    """Lenient probe: PIDs listening on TCP ``port``, or ``[]`` on probe failure.

    Use for best-effort cleanup (e.g. killing orphans). For start-up gating use
    ``assert_port_free``, which fails closed on probe errors.
    """
    try:
        return _probe_listening_pids(port)
    except PortProbeError:
        return []


def _list_listening_pids_windows(port: int) -> list[int]:
    try:
        out = subprocess.check_output(
            ["netstat", "-ano", "-p", "tcp"],
            text=True,
            errors="replace",
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PortProbeError(f"netstat probe failed: {exc}") from exc

    pids: set[int] = set()
    suffix = f":{port}"
    for line in out.splitlines():
        if "LISTENING" not in line.upper():
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        local = parts[1]
        if not (local.endswith(suffix) or local.endswith(f"]{suffix}")):
            continue
        try:
            pids.add(int(parts[-1]))
        except ValueError:
            continue
    return sorted(pids)


def _list_listening_pids_posix(port: int) -> list[int]:
    # Prefer `ss` (modern), fall back to `lsof`. `lsof -t` exits non-zero when
    # nothing matches, which is a legitimate empty result — treat exit code 1 as
    # "ran, found nothing" rather than a probe failure.
    any_success = False
    ss_out: str | None = None
    try:
        ss_out = subprocess.check_output(
            ["ss", "-ltnp", f"sport = :{port}"],
            text=True,
            errors="replace",
            stderr=subprocess.DEVNULL,
        )
        any_success = True
    except (OSError, subprocess.CalledProcessError):
        ss_out = None

    if ss_out is not None:
        pids: set[int] = set()
        for part in ss_out.replace(",", " ").split():
            if part.startswith("pid="):
                try:
                    pids.add(int(part.split("=", 1)[1]))
                except ValueError:
                    continue
        if pids:
            return sorted(pids)
        # ss ran and reported no listeners — definitive empty.
        return []

    lsof_cmd = ["lsof", f"-iTCP:{port}", "-sTCP:LISTEN", "-n", "-P", "-t"]
    try:
        proc = subprocess.run(
            lsof_cmd,
            text=True,
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        # lsof: 0 = matches, 1 = no matches (both are successful probes).
        if proc.returncode in (0, 1):
            any_success = True
            pids = set()
            for token in (proc.stdout or "").split():
                try:
                    pids.add(int(token.strip()))
                except ValueError:
                    continue
            return sorted(pids)
    except OSError:
        pass

    if not any_success:
        raise PortProbeError("no working port probe (ss/lsof unavailable)")
    return []


def describe_pid(pid: int) -> str:
    """Best-effort one-line description of a process (cmdline or name)."""
    if sys.platform == "win32":
        try:
            out = subprocess.check_output(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"(Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\").CommandLine",
                ],
                text=True,
                errors="replace",
                stderr=subprocess.DEVNULL,
                timeout=5,
            ).strip()
            if out:
                return out[:200]
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            pass
        return "python (details unavailable)"

    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            raw = fh.read().replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
            if raw:
                return raw[:200]
    except OSError:
        pass
    return "process (details unavailable)"


def assert_port_free(port: int, *, ignore_pids: Iterable[int] | None = None) -> None:
    """Exit with a clear message if ``port`` is already owned by other PIDs.

    Fails closed: if the OS listener table cannot be inspected, refuse to start
    (an unknown port state can hide a stale SO_REUSEADDR co-listener). Set
    ``PORT_GUARD_ALLOW_FAIL_OPEN=1`` to override in constrained environments.
    """
    ignore = {os.getpid(), *(ignore_pids or [])}
    try:
        pids = _probe_listening_pids(port)
    except PortProbeError as exc:
        if os.environ.get("PORT_GUARD_ALLOW_FAIL_OPEN") == "1":
            print(f"  WARNING: port {port} probe failed ({exc}); continuing "
                  f"because PORT_GUARD_ALLOW_FAIL_OPEN=1.")
            return
        raise SystemExit(
            "\n\n"
            f"PORT {port} STATE UNKNOWN — SERVER WILL NOT START\n\n"
            f"Could not inspect the OS listener table: {exc}\n"
            "Refusing to start to avoid a hidden duplicate listener.\n"
            "Set PORT_GUARD_ALLOW_FAIL_OPEN=1 to override.\n"
        )
    foreign = [pid for pid in pids if pid not in ignore]
    if not foreign:
        return

    lines = [
        "",
        "",
        f"PORT {port} ALREADY IN USE — SERVER WILL NOT START",
        "",
        "Another process is already listening on this port. On Windows, multiple",
        "Flask/Werkzeug servers can bind the same port (SO_REUSEADDR), and requests",
        "are routed nondeterministically — which serves stale code (e.g. missing ZIPs).",
        "",
        "Occupying process(es):",
    ]
    for pid in foreign:
        lines.append(f"  PID {pid}: {describe_pid(pid)}")
    lines += [
        "",
        "Fix:",
        f"  1. Preferred: python dev.py   (stops prior children, then starts clean)",
        f"  2. Or kill: Stop-Process -Id {foreign[0]} -Force",
        f"     (Unix: kill {foreign[0]})",
        "",
    ]
    raise SystemExit("\n".join(lines))
