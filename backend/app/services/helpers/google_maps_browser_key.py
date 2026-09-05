"""Resolve the browser-facing Google Maps / Places API key.

The SPA needs a Maps JavaScript + Places key for address autocomplete
(Quick Add, New Analysis, PropertyFactsForm). CI often builds the frontend
without ``VITE_GOOGLE_MAPS_API_KEY``, so production falls back to the key
configured on the backend (served to authenticated clients only).

Prefer a browser-restricted key when available; never return the placeholder.
"""
from __future__ import annotations

import os

_PLACEHOLDER = 'your-google-maps-api-key'

# Prefer an explicitly browser-scoped key, then the Vite-named env (sometimes
# copied into backend/.env), then the shared server Maps key.
_ENV_CANDIDATES = (
    'GOOGLE_MAPS_BROWSER_API_KEY',
    'VITE_GOOGLE_MAPS_API_KEY',
    'GOOGLE_MAPS_API_KEY',
)


def resolve_google_maps_browser_api_key() -> str | None:
    """Return a usable Maps browser API key, or ``None`` if unset/placeholder."""
    for name in _ENV_CANDIDATES:
        raw = (os.getenv(name) or '').strip()
        if not raw or raw == _PLACEHOLDER:
            continue
        return raw
    return None
