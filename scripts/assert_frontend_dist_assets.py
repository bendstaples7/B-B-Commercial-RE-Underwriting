#!/usr/bin/env python3
"""Assert every script/modulepreload href in dist/index.html exists on disk,
and that the built HTML satisfies the SPA chunk/boot contract.

Fails CI/Deploy when HTML references a missing hashed asset, or when Vite
regresses to a standalone react-*.js chunk.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DIST = REPO_ROOT / "frontend" / "dist"
INDEX = DIST / "index.html"

# Allow `python scripts/assert_frontend_dist_assets.py` without installing a package.
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from spa_html_contract import ASSET_HREF_RE, check_spa_html_contract  # noqa: E402


def main() -> int:
    if not INDEX.is_file():
        print(f"ERROR: missing {INDEX.relative_to(REPO_ROOT)} — run frontend build first")
        return 1

    html = INDEX.read_text(encoding="utf-8")
    contract = check_spa_html_contract(html, require_boot_watchdog=True)
    if not contract.ok:
        print("ERROR: dist/index.html failed SPA HTML contract:")
        for err in contract.errors:
            print(f"  - {err}")
        return 1

    hrefs = ASSET_HREF_RE.findall(html)
    asset_hrefs = [
        h for h in hrefs
        if "/assets/" in h or h.startswith("assets/")
    ]

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

    print(
        f"OK: SPA contract + {len(asset_hrefs)} asset href(s) "
        "in index.html exist under frontend/dist"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
