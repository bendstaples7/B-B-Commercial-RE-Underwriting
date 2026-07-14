"""HubSpot call disposition GUID → human-readable labels.

Default outcome IDs are stable per HubSpot docs (hs_call_disposition).
"""
from __future__ import annotations

import re

# https://developers.hubspot.com/docs/api-reference/latest/crm/activities/calls/guide
HUBSPOT_CALL_DISPOSITION_LABELS: dict[str, str] = {
    '9d9162e7-6cf3-4944-bf63-4dff82258764': 'Busy',
    'f240bbac-87c9-4f6e-bf70-924b57d47db7': 'Connected',
    'a4c4c377-d246-4b32-a13b-75a56a4cd0ff': 'Left live message',
    'b2cf5968-551e-4856-9783-52b3da59a7d0': 'Left voicemail',
    '73a0d17f-1163-4015-bdd5-ec830791da20': 'No answer',
    '17b47fee-58de-441e-a44c-c6300d46f273': 'Wrong number',
}

_UUID_RE = re.compile(
    r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
    re.IGNORECASE,
)

_CONNECTED_DISPOSITION_IDS = frozenset({
    'f240bbac-87c9-4f6e-bf70-924b57d47db7',
})


def looks_like_uuid(value: object) -> bool:
    """Return True when *value* is a bare UUID string."""
    if value is None:
        return False
    return bool(_UUID_RE.match(str(value).strip()))


def resolve_call_disposition_label(disposition: object | None) -> str | None:
    """Map a HubSpot disposition GUID or free-text outcome to a display label."""
    if disposition is None:
        return None
    text = str(disposition).strip()
    if not text:
        return None
    mapped = HUBSPOT_CALL_DISPOSITION_LABELS.get(text.lower())
    if mapped:
        return mapped
    if looks_like_uuid(text):
        return None
    return text.replace('_', ' ').strip() or None


def is_connected_disposition(disposition: object | None) -> bool:
    """True when the disposition indicates a connected/answered call."""
    if disposition is None:
        return False
    text = str(disposition).strip()
    if text.lower() in _CONNECTED_DISPOSITION_IDS:
        return True
    label = (resolve_call_disposition_label(text) or '').lower().strip()
    # Exact labels only — never substring (avoids "Not connected" / "Disconnected")
    return label in {'connected', 'answered'}


def format_hubspot_call_summary(
    *,
    body: str | None = None,
    title: str | None = None,
    disposition: object | None = None,
    direction: str | None = None,
    body_preview: str | None = None,
) -> str:
    """Build a human-readable HubSpot call summary.

    Prefer real note text, then mapped disposition, then title, then a generic
    direction-based fallback. Never returns a bare disposition UUID.
    """
    for candidate in (body, body_preview):
        text = (candidate or '').strip()
        if text and not looks_like_uuid(text):
            return text

    label = resolve_call_disposition_label(disposition)
    title_text = (title or '').strip()
    if label and title_text and not looks_like_uuid(title_text):
        return f'{title_text} — {label}'
    if label:
        return label
    if title_text and not looks_like_uuid(title_text):
        return title_text

    direction_text = (direction or '').strip().replace('_', ' ').title()
    if direction_text:
        return f'{direction_text} call'
    return 'HubSpot call'
