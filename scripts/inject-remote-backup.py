#!/usr/bin/env python3
"""
inject-remote-backup.py — Enable cloud backup settings in /home/deploy/backup.conf.

Called by the deploy workflow when B2_BUCKET_NAME is set.

Environment:
  B2_BUCKET_NAME       — private B2 bucket name
  B2_RCLONE_REMOTE     — rclone remote name (default: b2)
  B2_PATH_PREFIX       — remote path prefix (default: backups)
  REMOTE_METHOD        — transfer method (default: rclone)
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


def main() -> None:
    bucket = os.environ.get("B2_BUCKET_NAME", "").strip()
    if not bucket:
        print("NOTE: B2_BUCKET_NAME not set — skipping remote backup injection")
        raise SystemExit(0)

    if not CONF.is_file():
        print(f"ERROR: {CONF} does not exist", file=sys.stderr)
        raise SystemExit(1)

    remote = os.environ.get("B2_RCLONE_REMOTE", "b2").strip() or "b2"
    prefix = os.environ.get("B2_PATH_PREFIX", "backups").strip() or "backups"
    method = os.environ.get("REMOTE_METHOD", "rclone").strip() or "rclone"

    conf = CONF.read_text(encoding="utf-8")
    conf = set_var(conf, "REMOTE_METHOD", method)
    conf = set_var(conf, "RCLONE_REMOTE", remote)
    conf = set_var(conf, "RCLONE_BUCKET", bucket)
    conf = set_var(conf, "RCLONE_PATH_PREFIX", prefix)

    CONF.write_text(conf, encoding="utf-8")
    CONF.chmod(0o600)
    shutil.chown(CONF, user="deploy", group="deploy")
    print(f"NOTE: remote backup enabled — method={method} bucket={bucket} remote={remote}")


if __name__ == "__main__":
    main()
