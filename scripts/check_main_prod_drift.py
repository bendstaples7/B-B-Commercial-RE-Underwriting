#!/usr/bin/env python3
"""Compare origin/main (or --main-sha) to live /api/version; fail if drifted too long.

Catches "merged to main but Deploy never ran" after a grace window for normal
Deploy latency. Advisory when used from Ops canary.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def _git(*args: str, cwd: Path) -> str:
    out = subprocess.check_output(
        ["git", *args],
        cwd=cwd,
        text=True,
        stderr=subprocess.STDOUT,
    )
    return out.strip()


def fetch_prod_sha(version_url: str, timeout: float) -> str:
    req = urllib.request.Request(
        version_url,
        headers={"User-Agent": "bb-check-main-prod-drift/1.0", "Accept": "application/json"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    sha = (data.get("sha") or "").strip()
    if not sha or sha == "unknown":
        raise ValueError(f"/api/version returned unusable sha: {data!r}")
    return sha


def shas_match(main_sha: str, prod_sha: str) -> bool:
    main = main_sha.lower().strip()
    prod = prod_sha.lower().strip()
    if not main or not prod:
        return False
    if main == prod:
        return True
    # Allow short SHA forms either side
    n = min(len(main), len(prod), 40)
    if n < 7:
        return False
    return main[:n] == prod[:n] or main.startswith(prod) or prod.startswith(main)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        required=True,
        help="Prod origin (e.g. https://example.duckdns.org)",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
    )
    parser.add_argument(
        "--main-sha",
        default="",
        help="Override expected main SHA (default: origin/main or main)",
    )
    parser.add_argument(
        "--grace-minutes",
        type=int,
        default=45,
        help="Allow main to be ahead of prod for this many minutes after the main tip commit",
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    repo = args.repo_root
    main_sha = args.main_sha.strip()
    if not main_sha:
        for ref in ("origin/main", "main"):
            try:
                main_sha = _git("rev-parse", ref, cwd=repo)
                break
            except subprocess.CalledProcessError:
                continue
        if not main_sha:
            print("ERROR: could not resolve origin/main or main")
            return 1

    version_url = args.base_url.rstrip("/") + "/api/version"
    try:
        prod_sha = fetch_prod_sha(version_url, timeout=args.timeout)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: failed to read prod SHA from {version_url}: {exc}")
        return 1

    print(f"main_sha={main_sha}")
    print(f"prod_sha={prod_sha}")

    if shas_match(main_sha, prod_sha):
        print("OK: prod SHA matches main (no drift)")
        return 0

    # Drift — only fail after grace based on main tip commit time
    try:
        ts_raw = _git("show", "-s", "--format=%cI", main_sha, cwd=repo)
        main_time = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        if main_time.tzinfo is None:
            main_time = main_time.replace(tzinfo=timezone.utc)
    except (subprocess.CalledProcessError, ValueError) as exc:
        print(f"ERROR: could not read commit time for {main_sha}: {exc}")
        return 1

    age_sec = (datetime.now(timezone.utc) - main_time.astimezone(timezone.utc)).total_seconds()
    age_min = age_sec / 60.0
    print(f"main_tip_age_minutes={age_min:.1f} grace_minutes={args.grace_minutes}")

    if age_min < args.grace_minutes:
        print(
            f"OK: main is ahead of prod but within grace window "
            f"({age_min:.1f}m < {args.grace_minutes}m) — Deploy may still be in flight"
        )
        return 0

    print(
        "ERROR: main↔prod SHA drift exceeds grace window — "
        "fix may be merged but not deployed (hung App CI / skipped Deploy)."
    )
    print(f"  expected (main): {main_sha}")
    print(f"  live (prod):     {prod_sha}")
    print(f"  tip age:         {age_min:.1f} minutes")
    return 1


if __name__ == "__main__":
    sys.exit(main())
