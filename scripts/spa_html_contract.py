#!/usr/bin/env python3
"""Shared SPA HTML contract checks (dist and live).

Guards the blank-UI class where Vite split React into a separate chunk
(createContext on undefined). Used by:
  - scripts/assert_frontend_dist_assets.py (CI / Deploy artifact)
  - scripts/assert_live_spa_contract.py (prod / canary)
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Standalone React / ReactDOM runtime chunks only (Vite name: react-<hash>.js).
# Negative lookahead skips package chunks like react-router-*.js / react-select-*.js
# so a future manualChunk name cannot false-positive and roll back a healthy Deploy.
SEPARATE_REACT_CHUNK_RE = re.compile(
    r"""["'][^"']*/assets/react-(?!"""
    r"""(?:router|select|query|redux|hook-form|i18next|helmet|markdown)"""
    r"""(?:[-.]|$))"""
    r"""(?:dom-)?[A-Za-z0-9_-]{6,}\.js["']""",
    re.IGNORECASE,
)
VENDOR_ASSET_RE = re.compile(
    r"""["'][^"']*/assets/vendor-[^"'/]+\.js["']""",
    re.IGNORECASE,
)
ASSET_HREF_RE = re.compile(
    r"""<(?:script|link)\b[^>]*\b(?:src|href)=["']([^"']+)["']""",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SpaHtmlContractResult:
    ok: bool
    errors: tuple[str, ...]


def check_spa_html_contract(html: str, *, require_boot_watchdog: bool = True) -> SpaHtmlContractResult:
    """Validate served or built index HTML against SPA chunk/boot contracts."""
    errors: list[str] = []

    if SEPARATE_REACT_CHUNK_RE.search(html):
        errors.append(
            "HTML references a standalone /assets/react-*.js (or react-dom-*.js) chunk — "
            "React must ship inside vendor-*.js (createContext-on-undefined regression)"
        )

    if not VENDOR_ASSET_RE.search(html):
        errors.append(
            "HTML is missing /assets/vendor-*.js modulepreload/script "
            "(expected shared vendor chunk)"
        )

    if require_boot_watchdog and "spa-boot-failure" not in html:
        errors.append(
            "HTML is missing spa-boot-failure boot watchdog "
            "(frontend/index.html must keep the static watchdog)"
        )

    asset_hrefs = [
        h for h in ASSET_HREF_RE.findall(html)
        if "/assets/" in h or h.startswith("assets/")
    ]
    if not asset_hrefs:
        errors.append("HTML has no /assets/ script or modulepreload hrefs")

    return SpaHtmlContractResult(ok=not errors, errors=tuple(errors))
