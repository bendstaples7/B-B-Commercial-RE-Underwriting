#!/usr/bin/env python3
"""
configure_backup_remotes.py — Load JSON secrets and configure B2/Cloudflare independently.

Used by the deploy workflow. Secrets file is deleted in a finally block.
Exit 0 when at least one remote is configured, or when no cloud secrets were provided.
Exit 1 when credentials were provided but no remote ended up usable.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SECRETS_PATH = Path(os.environ.get("BACKUP_RCLONE_SECRETS_JSON", "/tmp/backup_rclone_secrets.json"))


def _run(script: str, env: dict[str, str]) -> int:
    return subprocess.run(
        [sys.executable, script],
        env=env,
        check=False,
    ).returncode


def main() -> None:
    try:
        if not SECRETS_PATH.is_file():
            print(f"ERROR: secrets file missing: {SECRETS_PATH}", file=sys.stderr)
            raise SystemExit(1)

        secrets = json.loads(SECRETS_PATH.read_text(encoding="utf-8"))
        if not isinstance(secrets, dict):
            print("ERROR: secrets JSON must be an object", file=sys.stderr)
            raise SystemExit(1)

        base_env = os.environ.copy()
        for key, value in secrets.items():
            if value is None:
                continue
            base_env[str(key)] = str(value)

        b2_key = (secrets.get("B2_KEY_ID") or "").strip()
        b2_app = (secrets.get("B2_APPLICATION_KEY") or "").strip()
        b2_bucket = (secrets.get("B2_BUCKET_NAME") or "").strip()
        cf_acct = (secrets.get("CLOUDFLARE_ACCOUNT_ID") or "").strip()
        cf_ak = (secrets.get("CLOUDFLARE_R2_ACCESS_KEY_ID") or "").strip()
        cf_sk = (secrets.get("CLOUDFLARE_R2_SECRET_ACCESS_KEY") or "").strip()
        cf_bucket = (secrets.get("CLOUDFLARE_R2_BUCKET_NAME") or "").strip()

        b2_wanted = bool(b2_key or b2_app or b2_bucket)
        cf_wanted = bool(cf_acct or cf_ak or cf_sk or cf_bucket)

        inject_env = base_env.copy()
        inject_env["B2_BUCKET_NAME"] = ""
        inject_env["CLOUDFLARE_R2_BUCKET_NAME"] = ""

        b2_ok = False
        cf_ok = False

        if b2_wanted:
            rc = _run("/home/deploy/setup-b2-rclone.py", base_env)
            # Only inject a B2 target when credentials were present and setup succeeded.
            # (Bucket-only secrets make setup skip with exit 0 — must not enable the target.)
            if rc == 0 and b2_key and b2_app and b2_bucket:
                b2_ok = True
                inject_env["B2_BUCKET_NAME"] = b2_bucket
            elif rc != 0:
                print(
                    "WARNING: setup-b2-rclone.py failed — continuing with other remotes",
                    file=sys.stderr,
                )
        else:
            print("NOTE: no Backblaze secrets — skipping B2 setup")

        if cf_wanted:
            rc = _run("/home/deploy/setup-cloudflare-rclone.py", base_env)
            if rc == 0 and cf_acct and cf_ak and cf_sk and cf_bucket:
                cf_ok = True
                inject_env["CLOUDFLARE_R2_BUCKET_NAME"] = cf_bucket
            elif rc != 0:
                print(
                    "WARNING: setup-cloudflare-rclone.py failed — continuing with other remotes",
                    file=sys.stderr,
                )
        else:
            print("NOTE: no Cloudflare secrets — skipping Cloudflare setup")

        inject_rc = _run("/home/deploy/inject-remote-backup.py", inject_env)
        if inject_rc != 0:
            print("ERROR: inject-remote-backup.py failed", file=sys.stderr)
            raise SystemExit(1)

        if b2_wanted or cf_wanted:
            if not b2_ok and not cf_ok:
                print(
                    "ERROR: cloud credentials were provided but no remote was configured",
                    file=sys.stderr,
                )
                raise SystemExit(1)

        print(
            "NOTE: backup remotes configured — "
            f"b2={'yes' if b2_ok else 'no'} cloudflare={'yes' if cf_ok else 'no'}"
        )
        raise SystemExit(0)
    finally:
        try:
            if SECRETS_PATH.is_file():
                SECRETS_PATH.write_text("", encoding="utf-8")
                SECRETS_PATH.unlink(missing_ok=True)
        except OSError as exc:
            print(f"WARNING: could not remove secrets file: {exc}", file=sys.stderr)


if __name__ == "__main__":
    main()
