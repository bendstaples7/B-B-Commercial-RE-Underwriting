#!/usr/bin/env python3
"""Fetch a live SPA index URL and assert the HTML SPA contract.

Used by Deploy (hard gate + rollback) and Ops canary (advisory).
"""
from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from spa_html_contract import check_spa_html_contract  # noqa: E402


def fetch_html(url: str, timeout: float) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "bb-assert-live-spa-contract/1.0",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        required=True,
        help="SPA origin or index URL (e.g. https://example.duckdns.org/)",
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    url = args.url.rstrip("/") + "/"
    try:
        html = fetch_html(url, timeout=args.timeout)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"ERROR: failed to fetch {url}: {exc}")
        return 1

    contract = check_spa_html_contract(html, require_boot_watchdog=True)
    if not contract.ok:
        print(f"ERROR: live SPA HTML contract failed for {url}:")
        for err in contract.errors:
            print(f"  - {err}")
        # Helpful excerpt for triage
        for line in html.splitlines():
            if "assets/" in line.lower() or "spa-boot" in line.lower():
                print(f"  html: {line.strip()[:200]}")
        return 1

    print(f"OK: live SPA HTML contract passed for {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
