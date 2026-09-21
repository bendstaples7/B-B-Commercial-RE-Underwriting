"""Resolve the browser-facing Google Maps / Places API key.

The SPA needs a Maps JavaScript + Places key for address autocomplete
(Quick Add, New Analysis, PropertyFactsForm). Prefer a dedicated browser key
(``GOOGLE_MAPS_BROWSER_API_KEY``, then ``VITE_GOOGLE_MAPS_API_KEY``). When
those are unset, fall back to ``GOOGLE_MAPS_API_KEY`` — the key already in
the platform env and previously used for Places autocomplete.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

_POLICY_PATH = Path(__file__).resolve().parents[4] / 'google_maps_browser_key_policy.json'
_POLICY = json.loads(_POLICY_PATH.read_text(encoding='utf-8'))

PLACEHOLDER_VALUES = frozenset(str(value) for value in _POLICY['placeholderValues'])
BROWSER_ENV_CANDIDATES = tuple(str(value) for value in _POLICY['browserEnvCandidates'])


def _normalize_key(raw: str | None) -> str | None:
    key = (raw or '').strip()
    if not key or key in PLACEHOLDER_VALUES:
        return None
    return key


def resolve_google_maps_browser_api_key() -> str | None:
    """Return a usable Maps browser API key, or ``None`` if unset/placeholder."""
    for name in BROWSER_ENV_CANDIDATES:
        key = _normalize_key(os.getenv(name))
        if key:
            return key
    return None
