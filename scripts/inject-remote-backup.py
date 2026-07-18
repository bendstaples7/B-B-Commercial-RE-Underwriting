#!/usr/bin/env python3
"""
inject-remote-backup.py — Enable cloud backup settings in /home/deploy/backup.conf.

Called by the deploy workflow when B2 and/or Cloudflare bucket secrets are set.

Environment:
  B2_BUCKET_NAME                 — Backblaze bucket name
  B2_RCLONE_REMOTE               — rclone remote name (default: b2)
  B2_PATH_PREFIX                 — remote path prefix (default: backups)
  CLOUDFLARE_R2_BUCKET_NAME      — Cloudflare bucket name
  CLOUDFLARE_RCLONE_REMOTE       — rclone remote name (default: cloudflare)
  REMOTE_METHOD                  — transfer method (default: rclone)
  REMOTE_RETENTION_DAYS          — default 14
  REMOTE_UPLOAD_HOUR_UTC         — default 10
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

CONF = Path("/home/deploy/backup.conf")


def set_var(conf: str, name: str, value: str) -> str:
    pattern = rf"^{name}=.*"
    replacement = f'{name}="{value}"'
    if re.search(pattern, conf, flags=re.MULTILINE):
        return re.sub(pattern, replacement, conf, flags=re.MULTILINE)
    return conf + f"{replacement}\n"


def normalize_upload_hour(value: str) -> str:
    """Return hour 0-23 as a decimal string without leading zeros (bash-safe).

    Values like ``08`` must not be written into backup.conf: Bash treats
    ``[[ 08 -eq 10 ]]`` as an octal literal and fails the comparison.
    """
    raw = (value or "").strip() or "10"
    try:
        hour = int(raw, 10)
    except ValueError as exc:
        raise ValueError(
            f"REMOTE_UPLOAD_HOUR_UTC must be an integer 0-23, got {value!r}"
        ) from exc
    if hour < 0 or hour > 23:
        raise ValueError(
            f"REMOTE_UPLOAD_HOUR_UTC must be an integer 0-23, got {value!r}"
        )
    return str(hour)


def build_rclone_targets(
    b2_bucket: str = "",
    cf_bucket: str = "",
    b2_remote: str = "b2",
    cf_remote: str = "cloudflare",
) -> str:
    """Return space-separated remote:bucket pairs for RCLONE_TARGETS."""
    targets: list[str] = []
    if b2_bucket.strip():
        targets.append(f"{b2_remote.strip() or 'b2'}:{b2_bucket.strip()}")
    if cf_bucket.strip():
        targets.append(f"{cf_remote.strip() or 'cloudflare'}:{cf_bucket.strip()}")
    return " ".join(targets)


def apply_remote_settings(
    conf: str,
    *,
    b2_bucket: str = "",
    cf_bucket: str = "",
    b2_remote: str = "b2",
    cf_remote: str = "cloudflare",
    prefix: str = "backups",
    method: str = "rclone",
    retention: str = "14",
    upload_hour: str = "10",
) -> str:
    """Return updated backup.conf text with dual-cloud remote settings."""
    targets_str = build_rclone_targets(b2_bucket, cf_bucket, b2_remote, cf_remote)
    if not targets_str:
        return conf

    hour = normalize_upload_hour(upload_hour)
    conf = set_var(conf, "REMOTE_METHOD", method)
    conf = set_var(conf, "RCLONE_TARGETS", targets_str)
    conf = set_var(conf, "RCLONE_PATH_PREFIX", prefix)
    conf = set_var(conf, "REMOTE_RETENTION_DAYS", retention)
    conf = set_var(conf, "REMOTE_UPLOAD_HOUR_UTC", hour)
    if b2_bucket.strip():
        conf = set_var(conf, "RCLONE_REMOTE", b2_remote.strip() or "b2")
        conf = set_var(conf, "RCLONE_BUCKET", b2_bucket.strip())
    elif cf_bucket.strip():
        conf = set_var(conf, "RCLONE_REMOTE", cf_remote.strip() or "cloudflare")
        conf = set_var(conf, "RCLONE_BUCKET", cf_bucket.strip())
    return conf


def main() -> None:
    b2_bucket = os.environ.get("B2_BUCKET_NAME", "").strip()
    cf_bucket = os.environ.get("CLOUDFLARE_R2_BUCKET_NAME", "").strip()
    if not b2_bucket and not cf_bucket:
        print(
            "NOTE: B2_BUCKET_NAME / CLOUDFLARE_R2_BUCKET_NAME not set — "
            "skipping remote backup injection"
        )
        raise SystemExit(0)

    if not CONF.is_file():
        print(f"ERROR: {CONF} does not exist", file=sys.stderr)
        raise SystemExit(1)

    b2_remote = os.environ.get("B2_RCLONE_REMOTE", "b2").strip() or "b2"
    cf_remote = (
        os.environ.get("CLOUDFLARE_RCLONE_REMOTE", "cloudflare").strip() or "cloudflare"
    )
    prefix = os.environ.get("B2_PATH_PREFIX", "backups").strip() or "backups"
    method = os.environ.get("REMOTE_METHOD", "rclone").strip() or "rclone"
    retention = os.environ.get("REMOTE_RETENTION_DAYS", "14").strip() or "14"
    upload_hour_raw = os.environ.get("REMOTE_UPLOAD_HOUR_UTC", "10").strip() or "10"
    try:
        upload_hour = normalize_upload_hour(upload_hour_raw)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    conf = CONF.read_text(encoding="utf-8")
    conf = apply_remote_settings(
        conf,
        b2_bucket=b2_bucket,
        cf_bucket=cf_bucket,
        b2_remote=b2_remote,
        cf_remote=cf_remote,
        prefix=prefix,
        method=method,
        retention=retention,
        upload_hour=upload_hour,
    )
    targets_str = build_rclone_targets(b2_bucket, cf_bucket, b2_remote, cf_remote)

    CONF.write_text(conf, encoding="utf-8")
    CONF.chmod(0o600)
    shutil.chown(CONF, user="deploy", group="deploy")
    print(
        "NOTE: remote backup enabled — "
        f"method={method} targets={targets_str} "
        f"retention={retention}d upload_hour_utc={upload_hour}"
    )


if __name__ == "__main__":
    main()
