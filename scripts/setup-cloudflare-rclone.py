#!/usr/bin/env python3
"""
setup-cloudflare-rclone.py — Configure rclone for Cloudflare object storage.

Called by the deploy workflow when Cloudflare secrets are present.

Environment:
  CLOUDFLARE_ACCOUNT_ID              — Cloudflare account ID (endpoint host)
  CLOUDFLARE_R2_ACCESS_KEY_ID        — S3-compatible access key ID
  CLOUDFLARE_R2_SECRET_ACCESS_KEY    — S3-compatible secret access key
  CLOUDFLARE_RCLONE_REMOTE           — rclone remote name (default: cloudflare)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> None:
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip().lower()
    access_key = os.environ.get("CLOUDFLARE_R2_ACCESS_KEY_ID", "").strip()
    secret_key = os.environ.get("CLOUDFLARE_R2_SECRET_ACCESS_KEY", "").strip()
    remote = os.environ.get("CLOUDFLARE_RCLONE_REMOTE", "cloudflare").strip() or "cloudflare"

    if not account_id or not access_key or not secret_key:
        print(
            "NOTE: Cloudflare rclone secrets not set — skipping Cloudflare rclone setup"
        )
        raise SystemExit(0)

    rclone_bin = shutil.which("rclone")
    if not rclone_bin:
        print(
            "ERROR: rclone not installed — install rclone before Cloudflare setup",
            file=sys.stderr,
        )
        raise SystemExit(1)

    config_dir = Path.home() / ".config" / "rclone"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "rclone.conf"

    if config_path.is_file():
        subprocess.run(
            [rclone_bin, "config", "delete", remote],
            check=False,
            capture_output=True,
        )

    endpoint = f"https://{account_id}.r2.cloudflarestorage.com"
    result = subprocess.run(
        [
            rclone_bin,
            "config",
            "create",
            remote,
            "s3",
            "provider",
            "Cloudflare",
            "access_key_id",
            access_key,
            "secret_access_key",
            secret_key,
            "endpoint",
            endpoint,
            "acl",
            "private",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(
            "ERROR: rclone config create failed:",
            result.stderr or result.stdout,
            file=sys.stderr,
        )
        raise SystemExit(1)

    os.chmod(config_path, 0o600)
    print(f"NOTE: rclone remote '{remote}' configured for Cloudflare object storage")


if __name__ == "__main__":
    main()
