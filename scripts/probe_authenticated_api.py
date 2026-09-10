#!/usr/bin/env python3
"""Login + GET one or more authenticated API paths (Deploy / Ops canary).

Credentials: SMOKE_TEST_EMAIL / SMOKE_TEST_PASSWORD (required unless --skip-if-no-creds).
Default path: /api/marketing/channel-roi (the intermittent Channel ROI load banner).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


DEFAULT_PATHS = ("/api/marketing/channel-roi",)


def _request(
    method: str,
    url: str,
    *,
    token: str | None = None,
    body: dict[str, Any] | None = None,
    timeout: float = 30.0,
) -> tuple[int, Any]:
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"refusing non-http(s) URL: {url!r}")
    headers = {
        "User-Agent": "bb-probe-authenticated-api/1.0",
        "Accept": "application/json",
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            raw = resp.read()
            status = int(resp.status)
    except urllib.error.HTTPError as exc:
        raw = exc.read() if exc.fp is not None else b""
        status = int(exc.code)
    except urllib.error.URLError as exc:
        raise SystemExit(f"ERROR: request failed for {url}: {exc}") from exc

    payload: Any
    if not raw:
        payload = None
    else:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = raw.decode("utf-8", errors="replace")
    return status, payload


def login(base_url: str, email: str, password: str, *, timeout: float) -> str:
    status, payload = _request(
        "POST",
        f"{base_url.rstrip('/')}/api/auth/login",
        body={"email": email, "password": password},
        timeout=timeout,
    )
    if status != 200 or not isinstance(payload, dict) or not payload.get("token"):
        raise SystemExit(
            f"ERROR: login failed (HTTP {status}): {payload!r}"
        )
    return str(payload["token"])


def probe_path(
    base_url: str,
    path: str,
    token: str,
    *,
    timeout: float,
    expect_json: bool,
) -> None:
    url = f"{base_url.rstrip('/')}{path if path.startswith('/') else '/' + path}"
    status, payload = _request("GET", url, token=token, timeout=timeout)
    if status != 200:
        raise SystemExit(
            f"ERROR: {path} returned HTTP {status} (expected 200). Body: {payload!r}"
        )
    if expect_json and not isinstance(payload, (dict, list)):
        raise SystemExit(
            f"ERROR: {path} returned HTTP 200 but body is not JSON object/array: "
            f"{type(payload).__name__}"
        )
    print(f"OK {path} HTTP {status}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        required=True,
        help="Public origin, e.g. https://example.duckdns.org",
    )
    parser.add_argument(
        "--path",
        action="append",
        dest="paths",
        help="Authenticated GET path (repeatable). Default: channel-roi.",
    )
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--skip-if-no-creds",
        action="store_true",
        help="Exit 0 when SMOKE_TEST_EMAIL/PASSWORD unset (Deploy/Ops skip).",
    )
    parser.add_argument(
        "--allow-non-json",
        action="store_true",
        help="Do not require a JSON object/array body.",
    )
    args = parser.parse_args(argv)

    email = (os.environ.get("SMOKE_TEST_EMAIL") or "").strip()
    password = (os.environ.get("SMOKE_TEST_PASSWORD") or "").strip()
    if not email or not password:
        if args.skip_if_no_creds:
            print("SMOKE_TEST_EMAIL/PASSWORD unset — skipping authenticated API probe.")
            return 0
        print("ERROR: SMOKE_TEST_EMAIL and SMOKE_TEST_PASSWORD are required.", file=sys.stderr)
        return 1

    paths = tuple(args.paths) if args.paths else DEFAULT_PATHS
    token = login(args.base_url, email, password, timeout=args.timeout)
    print(f"Login OK as {email}")
    for path in paths:
        probe_path(
            args.base_url,
            path,
            token,
            timeout=args.timeout,
            expect_json=not args.allow_non_json,
        )
    print("Authenticated API probe passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
