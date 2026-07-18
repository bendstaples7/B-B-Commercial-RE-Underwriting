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
    key_id = os.environ.get("B2_KEY_ID", "").strip()
    app_key = os.environ.get("B2_APPLICATION_KEY", "").strip()
    remote = os.environ.get("B2_RCLONE_REMOTE", "b2").strip() or "b2"

    flags = (_present(key_id), _present(app_key))
    if not any(flags):
        print("NOTE: B2_KEY_ID / B2_APPLICATION_KEY not set — skipping rclone B2 setup")
        raise SystemExit(0)
    if not all(flags):
        print(
            "ERROR: Backblaze credentials are partially configured "
            "(need B2_KEY_ID and B2_APPLICATION_KEY)",
            file=sys.stderr,
        )
        raise SystemExit(1)

    rclone_bin = shutil.which("rclone")
    if not rclone_bin:
        print("ERROR: rclone not installed — install rclone before B2 setup", file=sys.stderr)
        raise SystemExit(1)

    config_dir = Path.home() / ".config" / "rclone"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "rclone.conf"

    previous = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
    parser = configparser.ConfigParser()
    if previous:
        parser.read_string(previous)

    if not parser.has_section(remote):
        parser.add_section(remote)
    parser[remote]["type"] = "b2"
    parser[remote]["account"] = key_id
    parser[remote]["key"] = app_key

    fd, tmp_name = tempfile.mkstemp(prefix="rclone-", suffix=".conf", dir=str(config_dir))
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        with tmp_path.open("w", encoding="utf-8") as fh:
            parser.write(fh)
        os.chmod(tmp_path, 0o600)
        tmp_path.replace(config_path)
        os.chmod(config_path, 0o600)

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
        print(f"ERROR: rclone B2 config failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    print(f"NOTE: rclone remote '{remote}' configured for Backblaze B2")


if __name__ == "__main__":
    main()
