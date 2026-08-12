"""Lead Command Center mount health — count ULCC asset vs command-center API hits.

Pure helpers for nginx access-log scanning so CI can unit-test thresholds
without a live nginx. Used by scripts/check-lead-cc-mount-health.sh.

Loaded via importlib from bash — callers must register the module in
``sys.modules`` before ``exec_module`` (see check-lead-cc-mount-health.sh).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

# Combined log: ... [11/Aug/2026:14:47:43 +0000] "GET /assets/UnifiedLeadCommandCenter-….js …
LOG_LINE_RE = re.compile(
    r"\[(?P<ts>\d{2}/[A-Za-z]{3}/\d{4}:\d{2}:\d{2}:\d{2} [+-]\d{4})\]\s+"
    r'"(?P<method>GET|HEAD)\s+(?P<path>\S+)',
)

ULCC_PATH_RE = re.compile(r"/assets/UnifiedLeadCommandCenter-[^/?\s]+\.js(?:$|\?)")
CC_API_PATH_RE = re.compile(r"/api/leads/\d+/command-center")


@dataclass(frozen=True)
class MountHealthCounts:
    ulcc_loads: int
    command_center_hits: int
    window_start: datetime
    window_end: datetime


@dataclass(frozen=True)
class MountHealthDecision:
    unhealthy: bool
    reason: str
    counts: MountHealthCounts


def parse_nginx_ts(ts: str) -> datetime | None:
    """Parse nginx combined-log timestamp to aware UTC datetime."""
    try:
        # 11/Aug/2026:14:47:43 +0000
        dt = datetime.strptime(ts, "%d/%b/%Y:%H:%M:%S %z")
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def classify_path(path: str) -> str | None:
    """Return 'ulcc' | 'command_center' | None for a request path."""
    # Keep query for ULCC regex ($|\?); strip for API match.
    if ULCC_PATH_RE.search(path):
        return "ulcc"
    path_only = path.split("?", 1)[0]
    if CC_API_PATH_RE.search(path_only):
        return "command_center"
    return None


def count_mount_health(
    lines: Iterable[str],
    *,
    now: datetime | None = None,
    window_hours: float = 24.0,
) -> MountHealthCounts:
    """Count ULCC asset loads and command-center API hits in the time window."""
    end = now or datetime.now(timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    else:
        end = end.astimezone(timezone.utc)
    start = end - timedelta(hours=window_hours)

    ulcc = 0
    cc = 0
    for raw in lines:
        m = LOG_LINE_RE.search(raw)
        if not m:
            continue
        ts = parse_nginx_ts(m.group("ts"))
        if ts is None or ts < start or ts > end:
            continue
        kind = classify_path(m.group("path"))
        if kind == "ulcc":
            ulcc += 1
        elif kind == "command_center":
            cc += 1
    return MountHealthCounts(
        ulcc_loads=ulcc,
        command_center_hits=cc,
        window_start=start,
        window_end=end,
    )


def decide_mount_health(
    counts: MountHealthCounts,
    *,
    min_ulcc_zero_cc: int = 5,
    min_ulcc_ratio: int = 10,
    min_ratio: float = 0.1,
) -> MountHealthDecision:
    """Decide whether mount health is unhealthy enough to alert.

    Alert when:
      - ulcc_loads >= min_ulcc_zero_cc AND command_center_hits == 0, or
      - ulcc_loads >= min_ulcc_ratio AND command_center/ulcc < min_ratio
    """
    ulcc = counts.ulcc_loads
    cc = counts.command_center_hits

    if ulcc < min_ulcc_zero_cc:
        return MountHealthDecision(
            unhealthy=False,
            reason=f"insufficient traffic (ulcc={ulcc} < {min_ulcc_zero_cc})",
            counts=counts,
        )

    if cc == 0:
        return MountHealthDecision(
            unhealthy=True,
            reason=(
                f"ULCC JS loaded {ulcc} time(s) but command-center API hits=0 "
                f"in last window"
            ),
            counts=counts,
        )

    if ulcc >= min_ulcc_ratio:
        ratio = cc / ulcc
        if ratio < min_ratio:
            return MountHealthDecision(
                unhealthy=True,
                reason=(
                    f"command-center/ulcc ratio {ratio:.3f} < {min_ratio} "
                    f"(ulcc={ulcc}, command_center={cc})"
                ),
                counts=counts,
            )

    return MountHealthDecision(
        unhealthy=False,
        reason=f"healthy (ulcc={ulcc}, command_center={cc})",
        counts=counts,
    )
