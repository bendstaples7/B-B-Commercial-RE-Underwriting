#!/usr/bin/env python3
"""Backup health checks for verify-backup-health.sh and CI smoke tests."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def _load_backup_lib():
    deploy_lib = Path("/home/deploy/backup_lib.py")
    repo_lib = Path(__file__).resolve().parent.parent / "backup_lib.py"
    for candidate in (deploy_lib, repo_lib):
        if candidate.is_file():
            parent = str(candidate.parent)
            if parent not in sys.path:
                sys.path.insert(0, parent)
            from backup_lib import is_backup_stale

            return is_backup_stale
    raise ImportError("backup_lib.py not found")


def parse_backup_conf(path: Path) -> dict[str, str]:
    conf: dict[str, str] = {}
    if not path.is_file():
        return conf
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r'^([A-Z_]+)="([^"]*)"\s*$', line.strip())
        if match:
            conf[match.group(1)] = match.group(2)
    return conf


def read_crontab() -> str:
    try:
        return subprocess.check_output(["crontab", "-l"], text=True, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        return ""


def cron_missing_entries(crontab_text: str) -> list[str]:
    required = [
        ("/home/deploy/backup.sh", "scheduled backup.sh"),
        ("/home/deploy/pg-basebackup.sh", "weekly pg-basebackup.sh"),
        ("/home/deploy/daily-summary.sh", "daily-summary.sh"),
    ]
    missing: list[str] = []
    for needle, label in required:
        if needle not in crontab_text:
            missing.append(label)
    return missing


def parse_manifest_timestamp(ts: str) -> datetime:
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    parsed = datetime.fromisoformat(ts)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _entry_if_valid(entry: dict) -> dict | None:
    if entry.get("integrity") != "valid":
        return None
    ts = entry.get("timestamp")
    if not ts:
        return None
    try:
        parse_manifest_timestamp(ts)
    except (ValueError, TypeError):
        return None
    return entry


def last_valid_manifest_entry(manifest_path: Path) -> dict | None:
    if not manifest_path.is_file():
        return None
    valid: list[dict] = []
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        parsed = _entry_if_valid(entry)
        if parsed is not None:
            valid.append(parsed)
    return valid[-1] if valid else None


def recent_cloud_transfer_ok(manifest_path: Path, window_hours: int = 24) -> bool:
    """True if any valid manifest entry in the window uploaded to cloud."""
    if not manifest_path.is_file():
        return False
    now = datetime.now(timezone.utc)
    for line in reversed(manifest_path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("integrity") != "valid":
            continue
        ts = entry.get("timestamp")
        if not ts:
            continue
        try:
            parsed_ts = parse_manifest_timestamp(ts)
        except (ValueError, TypeError):
            continue
        transferred = entry.get("remote_transferred")
        if transferred is not True and transferred != "true":
            continue
        elapsed_hours = (now - parsed_ts).total_seconds() / 3600
        if elapsed_hours <= window_hours:
            return True
    return False


def estimate_remote_steady_state_gb(
    avg_dump_mb: float,
    dumps_per_day: int = 1,
    retention_days: int = 14,
) -> float:
    return dumps_per_day * retention_days * avg_dump_mb / 1024


# Backward-compatible alias (older docs/tests).
estimate_b2_steady_state_gb = estimate_remote_steady_state_gb


def run_checks(conf_path: Path = Path("/home/deploy/backup.conf")) -> list[str]:
    errors: list[str] = []
    conf = parse_backup_conf(conf_path)
    backup_dir = Path(conf.get("BACKUP_DIR", "/home/deploy/backups"))
    manifest_path = backup_dir / "backup_manifest.log"

    missing_cron = cron_missing_entries(read_crontab())
    if missing_cron:
        errors.append(f"missing cron entries: {', '.join(missing_cron)}")

    last = last_valid_manifest_entry(manifest_path)
    if last is None:
        errors.append("no valid backups in manifest")
        return errors

    is_stale_fn = _load_backup_lib()
    last_ts = parse_manifest_timestamp(last["timestamp"])
    now = datetime.now(timezone.utc)
    if is_stale_fn(last_ts, now):
        errors.append(f"backup stale — last valid entry at {last['timestamp']}")

    remote_method = conf.get("REMOTE_METHOD", "").strip()
    if remote_method:
        if not recent_cloud_transfer_ok(manifest_path):
            errors.append(
                "REMOTE_METHOD is set but no valid cloud-transferred backup found in the last 24 hours"
            )

    return errors


def main() -> None:
    errors = run_checks()
    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        sys.exit(1)
    print("OK: backup health checks passed")


if __name__ == "__main__":
    main()
