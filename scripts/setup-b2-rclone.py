#!/usr/bin/env python3
"""
setup-b2-rclone.py — Configure rclone for Backblaze B2 from environment variables.

Called by the deploy workflow when B2 secrets are present.

Environment:
  B2_KEY_ID            — Backblaze application key ID
  B2_APPLICATION_KEY   — Backblaze application key secret
  B2_RCLONE_REMOTE     — rclone remote name (default: b2)
  RCLONE_CONFIG_PASS   — optional; required when rclone.conf is encrypted
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


def _is_encrypted_rclone_conf(text: str) -> bool:
    head = text.lstrip()[:400].upper()
    return "RCLONE_ENCRYPT" in head or "ENCRYPTED RCLONE CONFIGURATION" in head


def _require_config_pass_for_encrypted(previous: str) -> None:
    if previous and _is_encrypted_rclone_conf(previous):
        if not os.environ.get("RCLONE_CONFIG_PASS", "").strip():
            raise RuntimeError(
                "rclone.conf is encrypted but RCLONE_CONFIG_PASS is not set; "
                "add the GitHub/Actions secret so deploy can update remotes"
            )


def _list_remotes(rclone_bin: str) -> list[str]:
    probe = subprocess.run(
        [rclone_bin, "listremotes"],
        check=False,
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        raise RuntimeError(
            (probe.stderr or probe.stdout or "rclone listremotes failed").strip()
        )
    return (probe.stdout or "").splitlines()


def _configure_via_rclone_cli(
    rclone_bin: str,
    remote: str,
    key_id: str,
    app_key: str,
) -> None:
    """Update/create remote through rclone so encrypted configs stay supported."""
    remotes = _list_remotes(rclone_bin)
    expected = f"{remote}:"
    if expected in remotes:
        cmd = [
            rclone_bin,
            "config",
            "update",
            remote,
            "type",
            "b2",
            "account",
            key_id,
            "key",
            app_key,
            "--non-interactive",
        ]
    else:
        cmd = [
            rclone_bin,
            "config",
            "create",
            remote,
            "b2",
            "account",
            key_id,
            "key",
            app_key,
            "--non-interactive",
        ]
    result = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            (result.stderr or result.stdout or "rclone config failed").strip()
        )
    remotes = _list_remotes(rclone_bin)
    if expected not in remotes:
        raise RuntimeError(f"rclone remote '{remote}' missing after config")


def _configure_via_ini(
    config_path: Path,
    previous: str,
    remote: str,
    key_id: str,
    app_key: str,
    rclone_bin: str,
) -> None:
    parser = configparser.ConfigParser(interpolation=None)
    if previous:
        parser.read_string(previous)

    if not parser.has_section(remote):
        parser.add_section(remote)
    parser[remote]["type"] = "b2"
    parser[remote]["account"] = key_id
    parser[remote]["key"] = app_key

    fd, tmp_name = tempfile.mkstemp(prefix="rclone-", suffix=".conf", dir=str(config_path.parent))
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        with tmp_path.open("w", encoding="utf-8") as fh:
            parser.write(fh)
        os.chmod(tmp_path, 0o600)
        tmp_path.replace(config_path)
        os.chmod(config_path, 0o600)
        remotes = _list_remotes(rclone_bin)
        if f"{remote}:" not in remotes:
            raise RuntimeError("rclone listremotes did not include the new B2 remote")
    finally:
        tmp_path.unlink(missing_ok=True)


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
    previous_bytes = config_path.read_bytes() if config_path.is_file() else None

    try:
        _require_config_pass_for_encrypted(previous)
        if previous and _is_encrypted_rclone_conf(previous):
            _configure_via_rclone_cli(rclone_bin, remote, key_id, app_key)
        else:
            _configure_via_ini(
                config_path, previous, remote, key_id, app_key, rclone_bin
            )
    except Exception as exc:
        if previous_bytes is not None:
            config_path.write_bytes(previous_bytes)
            os.chmod(config_path, 0o600)
        elif config_path.is_file() and previous_bytes is None:
            config_path.unlink(missing_ok=True)
        print(f"ERROR: rclone B2 config failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"NOTE: rclone remote '{remote}' configured for Backblaze B2")


if __name__ == "__main__":
    main()
