#!/usr/bin/env python3
"""Assert every script/modulepreload href in dist/index.html exists on disk,
and that the built HTML satisfies the SPA chunk/boot contract.

Fails CI/Deploy when HTML references a missing hashed asset, when Vite
regresses to a standalone react-*.js chunk, or when a lazy route chunk
imports the entry index-*.js (circular lazy↔entry graph).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DIST = REPO_ROOT / "frontend" / "dist"
INDEX = DIST / "index.html"

# Allow `python scripts/assert_frontend_dist_assets.py` without installing a package.
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from spa_html_contract import ASSET_HREF_RE, check_spa_html_contract  # noqa: E402

# Shared / vendor chunks are allowed to be pulled by the entry; other hashed
# JS under assets/ must not import back into index-*.js (lazy↔entry cycle).
SHARED_CHUNK_PREFIXES = (
    "index-",
    "vendor-",
    "mui-",
    "api-",
    "ui-shared-",
    "maps-",
    "ag-grid-",
    "recharts-",
    "dnd-",
    # Auto-split shared helpers (not route entrypoints)
    "helpers-",
    "formatters-",
    "pagination-",
    "phone-",
    "leadStatuses-",
    "queueQueryDefaults-",
    "queueRowActions-",
    "commandCenterChrome-",
    "outreachContact-",
    "prospectMotivation-",
    "scoringRecommendedActions-",
    "formatEnqueueSummary-",
    "cookCountyPin-",
    "useQueueSelection-",
)

# Static `from"./index-` / `from'./index-` and dynamic `import("./index-…)`.
INDEX_IMPORT_RE = re.compile(
    r"""from\s*["']\./index-|import\s*\(\s*["']\./index-"""
)


def is_lazy_route_chunk(name: str) -> bool:
    if not name.endswith(".js"):
        return False
    return not any(name.startswith(prefix) for prefix in SHARED_CHUNK_PREFIXES)


def find_lazy_chunks_importing_index(assets_dir: Path) -> list[str]:
    offenders: list[str] = []
    if not assets_dir.is_dir():
        return offenders
    for path in sorted(assets_dir.glob("*.js")):
        if not is_lazy_route_chunk(path.name):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if INDEX_IMPORT_RE.search(text):
            offenders.append(path.name)
    return offenders


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

    assets_dir = DIST / "assets"
    ulcc_files = sorted(assets_dir.glob("UnifiedLeadCommandCenter-*.js"))
    if not ulcc_files:
        print("ERROR: no UnifiedLeadCommandCenter-*.js under frontend/dist/assets")
        return 1

    offenders = find_lazy_chunks_importing_index(assets_dir)
    if offenders:
        print(
            "ERROR: lazy route chunk(s) import entry index-*.js "
            "(lazy<->entry cycle — can blank routes):"
        )
        for name in offenders:
            print(f"  - {name}")
        return 1

    lazy_count = sum(
        1 for p in assets_dir.glob("*.js") if is_lazy_route_chunk(p.name)
    )
    print(
        f"OK: {lazy_count} lazy route chunk(s) do not import entry index-*.js "
        f"(including {ulcc_files[0].name})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
