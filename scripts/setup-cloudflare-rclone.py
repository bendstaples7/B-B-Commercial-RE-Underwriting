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

import configparser
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _present(value: str) -> bool:
    return bool(value.strip())


def main() -> None:
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip().lower()
    access_key = os.environ.get("CLOUDFLARE_R2_ACCESS_KEY_ID", "").strip()
    secret_key = os.environ.get("CLOUDFLARE_R2_SECRET_ACCESS_KEY", "").strip()
    remote = os.environ.get("CLOUDFLARE_RCLONE_REMOTE", "cloudflare").strip() or "cloudflare"

    flags = (_present(account_id), _present(access_key), _present(secret_key))
    if not any(flags):
        print(
            "NOTE: Cloudflare rclone secrets not set — skipping Cloudflare rclone setup"
        )
        raise SystemExit(0)
    if not all(flags):
        print(
            "ERROR: Cloudflare credentials are partially configured "
            "(need CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_R2_ACCESS_KEY_ID, "
            "CLOUDFLARE_R2_SECRET_ACCESS_KEY)",
            file=sys.stderr,
        )
        raise SystemExit(1)

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

    previous = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
    parser = configparser.ConfigParser()
    if previous:
        parser.read_string(previous)

    section = remote
    if not parser.has_section(section):
        parser.add_section(section)
    parser[section]["type"] = "s3"
    parser[section]["provider"] = "Cloudflare"
    parser[section]["access_key_id"] = access_key
    parser[section]["secret_access_key"] = secret_key
    parser[section]["endpoint"] = f"https://{account_id}.r2.cloudflarestorage.com"
    parser[section]["acl"] = "private"

    fd, tmp_name = tempfile.mkstemp(prefix="rclone-", suffix=".conf", dir=str(config_dir))
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        with tmp_path.open("w", encoding="utf-8") as fh:
            parser.write(fh)
        os.chmod(tmp_path, 0o600)
        tmp_path.replace(config_path)
        os.chmod(config_path, 0o600)

        # Validate without printing secrets.
        probe = subprocess.run(
            [rclone_bin, "listremotes"],
            check=False,
            capture_output=True,
            text=True,
        )
        remotes = (probe.stdout or "").splitlines()
        expected = f"{remote}:"
        if probe.returncode != 0 or expected not in remotes:
            raise RuntimeError(
                (probe.stderr or probe.stdout or "rclone listremotes failed").strip()
            )
    except Exception as exc:
        if previous:
            config_path.write_text(previous, encoding="utf-8")
            os.chmod(config_path, 0o600)
        elif config_path.is_file() and not previous:
            config_path.unlink(missing_ok=True)
        print(f"ERROR: rclone Cloudflare config failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    print(f"NOTE: rclone remote '{remote}' configured for Cloudflare object storage")


if __name__ == "__main__":
    main()
