#!/usr/bin/env python3
"""
setup-cloudflare-rclone.py — Configure rclone for Cloudflare object storage.

Called by the deploy workflow when Cloudflare secrets are present.

Environment:
  CLOUDFLARE_ACCOUNT_ID              — Cloudflare account ID (endpoint host)
  CLOUDFLARE_R2_ACCESS_KEY_ID        — S3-compatible access key ID
  CLOUDFLARE_R2_SECRET_ACCESS_KEY    — S3-compatible secret access key
  CLOUDFLARE_RCLONE_REMOTE           — rclone remote name (default: cloudflare)
  RCLONE_CONFIG_PASS                 — optional; required when rclone.conf is encrypted
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
    access_key: str,
    secret_key: str,
    endpoint: str,
) -> None:
    """Update/create remote through rclone so encrypted configs stay supported."""
    remotes = _list_remotes(rclone_bin)
    expected = f"{remote}:"
    kv = [
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
    ]
    if expected in remotes:
        cmd = [rclone_bin, "config", "update", remote, "type", "s3", *kv, "--non-interactive"]
    else:
        cmd = [rclone_bin, "config", "create", remote, "s3", *kv, "--non-interactive"]
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
    access_key: str,
    secret_key: str,
    endpoint: str,
    rclone_bin: str,
) -> None:
    parser = configparser.ConfigParser(interpolation=None)
    if previous:
        parser.read_string(previous)

    if not parser.has_section(remote):
        parser.add_section(remote)
    parser[remote]["type"] = "s3"
    parser[remote]["provider"] = "Cloudflare"
    parser[remote]["access_key_id"] = access_key
    parser[remote]["secret_access_key"] = secret_key
    parser[remote]["endpoint"] = endpoint
    parser[remote]["acl"] = "private"

    fd, tmp_name = tempfile.mkstemp(
        prefix="rclone-", suffix=".conf", dir=str(config_path.parent)
    )
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
            raise RuntimeError(
                "rclone listremotes did not include the new Cloudflare remote"
            )
    finally:
        tmp_path.unlink(missing_ok=True)


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
    endpoint = f"https://{account_id}.r2.cloudflarestorage.com"

    previous = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
    previous_bytes = config_path.read_bytes() if config_path.is_file() else None

    try:
        _require_config_pass_for_encrypted(previous)
        if previous and _is_encrypted_rclone_conf(previous):
            _configure_via_rclone_cli(
                rclone_bin, remote, access_key, secret_key, endpoint
            )
        else:
            _configure_via_ini(
                config_path,
                previous,
                remote,
                access_key,
                secret_key,
                endpoint,
                rclone_bin,
            )
    except Exception as exc:
        if previous_bytes is not None:
            config_path.write_bytes(previous_bytes)
            os.chmod(config_path, 0o600)
        elif config_path.is_file() and previous_bytes is None:
            config_path.unlink(missing_ok=True)
        print(f"ERROR: rclone Cloudflare config failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"NOTE: rclone remote '{remote}' configured for Cloudflare object storage")


if __name__ == "__main__":
    main()
