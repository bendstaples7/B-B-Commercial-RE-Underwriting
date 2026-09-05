#!/usr/bin/env python3
"""Inject window.__BB_GOOGLE_MAPS_API_KEY__ into a built SPA index.html.

CI often builds the frontend without VITE_GOOGLE_MAPS_API_KEY, leaving
``googleMapsApiKey:""`` in the bundle. Deploy reads a browser-scoped key from
backend/.env (or repo-root .env) and injects a small bootstrap script so
authenticated clients can load Places autocomplete without a rebuild.

Usage:
  python3.11 scripts/inject_google_maps_browser_key.py frontend/dist/index.html
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_POLICY_PATH = Path(__file__).resolve().parents[1] / 'google_maps_browser_key_policy.json'
_POLICY = json.loads(_POLICY_PATH.read_text(encoding='utf-8'))

PLACEHOLDER_VALUES = frozenset(str(value) for value in _POLICY['placeholderValues'])
MARKER_START = '<!-- bb-google-maps-api-key -->'
MARKER_END = '<!-- /bb-google-maps-api-key -->'
ENV_CANDIDATES = tuple(str(value) for value in _POLICY['browserEnvCandidates'])


def _load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or '=' not in stripped:
            continue
        key, _, raw = stripped.partition('=')
        key = key.strip()
        val = raw.strip().strip("'").strip('"')
        if key:
            values[key] = val
    return values


def resolve_key(app_dir: Path) -> str | None:
    merged: dict[str, str] = {}
    for rel in ('.env', 'backend/.env'):
        merged.update(_load_dotenv(app_dir / rel))
    for name in ENV_CANDIDATES:
        raw = (os.environ.get(name) or merged.get(name) or '').strip()
        if raw and raw not in PLACEHOLDER_VALUES:
            return raw
    return None


def inject(index_html: Path, api_key: str) -> bool:
    text = index_html.read_text(encoding='utf-8')
    # JSON-encode for JavaScript, then escape HTML script terminators.
    safe = json.dumps(api_key).replace('</', '<\\/')
    snippet = (
        f'{MARKER_START}\n'
        f'<script>window.__BB_GOOGLE_MAPS_API_KEY__={safe};</script>\n'
        f'{MARKER_END}\n'
    )
    if MARKER_START in text and MARKER_END in text:
        before, _, rest = text.partition(MARKER_START)
        _, _, after = rest.partition(MARKER_END)
        text = f'{before}{snippet}{after.lstrip(chr(10))}'
    else:
        needle = '<div id="root"></div>'
        if needle not in text:
            print(f'FAILED: could not find injection point in {index_html}', file=sys.stderr)
            return False
        text = text.replace(needle, f'{needle}\n{snippet}', 1)
    index_html.write_text(text, encoding='utf-8')
    return True


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f'Usage: {argv[0]} <path-to-index.html>', file=sys.stderr)
        return 2
    index_html = Path(argv[1]).resolve()
    if not index_html.is_file():
        print(f'FAILED: {index_html} not found', file=sys.stderr)
        return 1
    # Prefer APP_DIR / deploy layout; fall back to repo root inferred from script.
    app_dir = Path(os.environ.get('APP_DIR') or index_html.parents[2])
    api_key = resolve_key(app_dir)
    if not api_key:
        print('SKIP: no Google Maps browser API key in env/.env')
        return 0
    if not inject(index_html, api_key):
        return 1
    print(f'Injected Google Maps browser API key into {index_html}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
