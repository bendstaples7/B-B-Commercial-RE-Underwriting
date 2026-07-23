"""Normalize ``leads.mailer_history`` JSONB into a readable row list.

Handles legacy free-text strings (HubSpot/import era), OLC dict entries, and
mixed arrays. Canonical for API serializers (command-center payload); the FE
prefers ``mailer_history_summary`` from the API when present.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

# Trailing date in legacy strings like "Boyfriend, OLM, Blue,  6/21/2024"
_LEGACY_DATE_RE = re.compile(
    r'(?P<label>.*?),\s*(?P<date>\d{1,2}/\d{1,2}/\d{2,4})\s*$',
)


def _as_entries(raw: Any) -> list[Any]:
    if raw is None or raw == '' or raw == []:
        return []
    if isinstance(raw, list):
        return list(raw)
    return [raw]


def parse_mailer_sent_at(value: Any) -> datetime | None:
    """Parse ISO or US slash dates for ordering; None when unparseable."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith('Z'):
        text = text[:-1] + '+00:00'
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        pass
    for fmt in ('%m/%d/%Y', '%m/%d/%y', '%Y-%m-%d', '%Y/%m/%d'):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def normalize_mailer_history(raw: Any) -> list[dict[str, Any]]:
    """Return stable mail-history rows for UI.

    Each row:
      id, sent_at, label, creative, template_name, campaign_id,
      olc_order_id, address_feedback, cancelled, source
    """
    rows: list[dict[str, Any]] = []
    for idx, entry in enumerate(_as_entries(raw)):
        row = _normalize_one(entry, idx)
        if row is not None:
            rows.append(row)
    return rows


def _normalize_one(entry: Any, idx: int) -> dict[str, Any] | None:
    if entry is None or entry == '':
        return None

    if isinstance(entry, dict):
        sent_at = entry.get('sent_at')
        template_name = entry.get('template_name')
        creative = entry.get('creative')
        label_parts = [p for p in (template_name, creative) if p]
        label = ', '.join(str(p) for p in label_parts) if label_parts else None
        if not label and entry.get('olc_order_id'):
            label = f"OLC order {entry.get('olc_order_id')}"
        if not label and entry.get('campaign_id') is not None:
            label = f"Campaign {entry.get('campaign_id')}"
        if not label and entry.get('address_feedback'):
            label = f"Address feedback: {entry.get('address_feedback')}"
        if not label:
            label = 'Mailer'
        source = 'olc' if (
            entry.get('campaign_id') is not None or entry.get('olc_order_id')
        ) else 'imported'
        return {
            'id': f'mail-{idx}',
            'sent_at': sent_at if sent_at is None else str(sent_at),
            'label': label,
            'creative': creative,
            'template_name': template_name,
            'campaign_id': entry.get('campaign_id'),
            'olc_order_id': entry.get('olc_order_id'),
            'address_feedback': entry.get('address_feedback'),
            'cancelled': bool(entry.get('cancelled')),
            'source': source,
        }

    text = str(entry).strip()
    if not text:
        return None
    match = _LEGACY_DATE_RE.match(text)
    if match:
        return {
            'id': f'mail-{idx}',
            'sent_at': match.group('date'),
            'label': match.group('label').strip().rstrip(','),
            'creative': None,
            'template_name': None,
            'campaign_id': None,
            'olc_order_id': None,
            'address_feedback': None,
            'cancelled': False,
            'source': 'imported',
        }
    return {
        'id': f'mail-{idx}',
        'sent_at': None,
        'label': text,
        'creative': None,
        'template_name': None,
        'campaign_id': None,
        'olc_order_id': None,
        'address_feedback': None,
        'cancelled': False,
        'source': 'imported',
    }


def mailer_history_summary(raw: Any) -> dict[str, Any]:
    """Count + last sent_at for summary chips (date-aware ordering)."""
    rows = normalize_mailer_history(raw)
    last_sent = None
    last_dt: datetime | None = None
    for row in rows:
        sent = row.get('sent_at')
        if not sent:
            continue
        parsed = parse_mailer_sent_at(sent)
        if parsed is not None:
            if last_dt is None or parsed > last_dt:
                last_dt = parsed
                last_sent = sent
        elif last_sent is None:
            last_sent = str(sent)
    return {
        'count': len(rows),
        'last_sent_at': last_sent,
        'rows': rows,
    }
