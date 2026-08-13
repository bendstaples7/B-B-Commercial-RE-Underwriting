#!/usr/bin/env python3
"""Fetch a live SPA index URL and assert the HTML SPA contract + asset HTTP 200.

Used by Deploy (hard gate + rollback) and Ops canary (advisory).

Asset reachability catches the blank-SPA class where index.html is served but
nginx cannot traverse frontend/dist/assets (e.g. mode 0700 → HTTP 404).
"""
from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urljoin

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from spa_html_contract import ASSET_HREF_RE, check_spa_html_contract  # noqa: E402


def _fetch_once(url: str, timeout: float) -> tuple[int, bytes, str]:
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"refusing non-http(s) URL: {url!r}")
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "bb-assert-live-spa-contract/1.0",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        charset = resp.headers.get_content_charset() or "utf-8"
        return int(resp.status), resp.read(), charset


def fetch_html(url: str, timeout: float, *, attempts: int = 3) -> str:
    """Fetch HTML with short backoff so a single blip cannot trigger Deploy rollback."""
    last_exc: BaseException | None = None
    for attempt in range(max(1, attempts)):
        try:
            _status, body, charset = _fetch_once(url, timeout)
            return body.decode(charset, errors="replace")
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            last_exc = exc
            if attempt < attempts - 1:
                delay = 2 * (attempt + 1)
                print(
                    f"WARN: fetch {url} attempt {attempt + 1}/{attempts} failed "
                    f"({exc}); retrying in {delay}s..."
                )
                time.sleep(delay)
    assert last_exc is not None
    raise last_exc


def asset_urls_from_html(html: str, base_url: str) -> list[str]:
    """Absolute URLs for /assets/ script and link hrefs in index HTML."""
    out: list[str] = []
    seen: set[str] = set()
    for href in ASSET_HREF_RE.findall(html):
        path = href.split("?", 1)[0]
        if "/assets/" not in path and not path.startswith("assets/"):
            continue
        abs_url = urljoin(base_url, path)
        if abs_url in seen:
            continue
        seen.add(abs_url)
        out.append(abs_url)
    return out


def fetch_status(url: str, timeout: float, *, attempts: int = 3) -> int:
    """Return HTTP status; retry transport and 5xx failures before giving up."""
    last_status = 0
    for attempt in range(max(1, attempts)):
        try:
            status, _body, _charset = _fetch_once(url, timeout)
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            status = 0
            if attempt < attempts - 1:
                delay = 2 * (attempt + 1)
                print(
                    f"WARN: asset fetch {url} attempt {attempt + 1}/{attempts} failed "
                    f"({exc}); retrying in {delay}s..."
                )
                time.sleep(delay)
                continue
        last_status = status
        if status == 0 or status >= 500:
            if attempt < attempts - 1:
                delay = 2 * (attempt + 1)
                print(
                    f"WARN: asset fetch {url} attempt {attempt + 1}/{attempts} "
                    f"returned HTTP {status}; retrying in {delay}s..."
                )
                time.sleep(delay)
                continue
        return status
    return last_status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        required=True,
        help="SPA origin or index URL (e.g. https://example.duckdns.org/)",
    )
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument(
        "--skip-assets",
        action="store_true",
        help="Only check HTML contract (tests / emergency bypass)",
    )
    args = parser.parse_args()

    url = args.url if args.url.endswith(("/", ".html")) else args.url.rstrip("/") + "/"
    try:
        html = fetch_html(url, timeout=args.timeout)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
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

    if args.skip_assets:
        return 0

    asset_urls = asset_urls_from_html(html, url)
    if not asset_urls:
        print(f"ERROR: no /assets/ hrefs found in {url}")
        return 1

    failed: list[str] = []
    for asset_url in asset_urls:
        status = fetch_status(asset_url, timeout=args.timeout)
        if status != 200:
            failed.append(f"{asset_url} -> HTTP {status}")
        else:
            print(f"OK: asset HTTP 200 {asset_url}")

    if failed:
        print(
            "ERROR: live SPA assets not reachable "
            "(nginx cannot serve hashed JS — often mode 0700 on assets/):"
        )
        for line in failed:
            print(f"  - {line}")
        return 1

    print(f"OK: {len(asset_urls)} live SPA asset(s) returned HTTP 200")
    return 0


if __name__ == "__main__":
    sys.exit(main())
