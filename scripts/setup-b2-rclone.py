#!/usr/bin/env python3
"""
setup-b2-rclone.py — Configure rclone for Backblaze B2 from environment variables.

Called by the deploy workflow when B2 secrets are present.

Environment:
  B2_KEY_ID            — Backblaze application key ID
  B2_APPLICATION_KEY   — Backblaze application key secret
  B2_RCLONE_REMOTE     — rclone remote name (default: b2)
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    key_id = os.environ.get("B2_KEY_ID", "").strip()
    app_key = os.environ.get("B2_APPLICATION_KEY", "").strip()
    remote = os.environ.get("B2_RCLONE_REMOTE", "b2").strip() or "b2"

    if not key_id or not app_key:
        print("NOTE: B2_KEY_ID / B2_APPLICATION_KEY not set — skipping rclone B2 setup")
        raise SystemExit(0)

    config_dir = Path.home() / ".config" / "rclone"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "rclone.conf"

    # Remove stale remote so credentials can be refreshed on redeploy.
    if config_path.is_file():
        subprocess.run(
            ["rclone", "config", "delete", remote],
            check=False,
            capture_output=True,
        )

    result = subprocess.run(
        [
            "rclone",
            "config",
            "create",
            remote,
            "b2",
            "account",
            key_id,
            "key",
            app_key,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("ERROR: rclone config create failed:", result.stderr or result.stdout, file=sys.stderr)
        raise SystemExit(1)

    os.chmod(config_path, 0o600)
    print(f"NOTE: rclone remote '{remote}' configured for Backblaze B2")


if __name__ == "__main__":
    main()
