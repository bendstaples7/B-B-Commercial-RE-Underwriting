#!/usr/bin/env python3
"""Assert every script/modulepreload href in dist/index.html exists on disk.

Fails CI/Deploy when HTML references a missing hashed asset (mismatched dist).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DIST = REPO_ROOT / "frontend" / "dist"
INDEX = DIST / "index.html"

HREF_RE = re.compile(
    r"""<(?:script|link)\b[^>]*\b(?:src|href)=["']([^"']+)["']""",
    re.IGNORECASE,
)


def main() -> int:
    if not INDEX.is_file():
        print(f"ERROR: missing {INDEX.relative_to(REPO_ROOT)} — run frontend build first")
        return 1

    html = INDEX.read_text(encoding="utf-8")
    hrefs = HREF_RE.findall(html)
    asset_hrefs = [
        h for h in hrefs
        if "/assets/" in h or h.startswith("assets/")
    ]
    if not asset_hrefs:
        print("ERROR: dist/index.html has no /assets/ script or modulepreload hrefs")
        return 1

    missing: list[str] = []
    for href in asset_hrefs:
        # "/assets/foo.js" → frontend/dist/assets/foo.js
        rel = href.split("?", 1)[0].lstrip("/")
        path = DIST / rel
        if not path.is_file():
            missing.append(href)

    if missing:
        print("ERROR: index.html references missing assets:")
        for href in missing:
            print(f"  - {href}")
        return 1

    print(f"OK: {len(asset_hrefs)} asset href(s) in index.html exist under frontend/dist")
    return 0


if __name__ == "__main__":
    sys.exit(main())
