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


def _last_sent_from_rows(rows: list[dict[str, Any]]) -> Any:
    """Date-aware last-sent lookup shared by summary + consolidate."""
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
    return last_sent


def mailer_history_summary(raw: Any) -> dict[str, Any]:
    """Count + last sent_at for summary chips (date-aware ordering)."""
    rows = normalize_mailer_history(raw)
    return {
        'count': len(rows),
        'last_sent_at': _last_sent_from_rows(rows),
        'rows': rows,
    }


def _present_identifier(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _dedupe_keys(row: dict[str, Any]) -> set[tuple[str, str | None, str | None]]:
    """Identities for a mail-history row.

    OLC-backed rows can arrive with only one of campaign_id / olc_order_id, or
    with numeric IDs represented as strings. Treat any shared normalized OLC
    identifier as the same send; fall back to text identity for legacy rows.
    """
    campaign_id = row.get('campaign_id')
    olc_order_id = row.get('olc_order_id')
    keys: set[tuple[str, str | None, str | None]] = set()
    normalized_campaign_id = _present_identifier(campaign_id)
    normalized_olc_order_id = _present_identifier(olc_order_id)
    if normalized_campaign_id is not None:
        keys.add(('olc-campaign', normalized_campaign_id, None))
    if normalized_olc_order_id is not None:
        keys.add(('olc-order', normalized_olc_order_id, None))
    if keys:
        return keys
    return {('text', _present_identifier(row.get('sent_at')), _present_identifier(row.get('label')))}


def _timeline_mail_sent_rows(lead: Any) -> list[dict[str, Any]]:
    """Normalize ``mail_sent`` LeadTimelineEntry rows into the mail-history shape."""
    lead_id = getattr(lead, 'id', None)
    if not lead_id:
        return []
    from app.models.lead_timeline_entry import LeadTimelineEntry

    entries = (
        LeadTimelineEntry.query.filter(
            LeadTimelineEntry.lead_id == lead_id,
            LeadTimelineEntry.event_type == 'mail_sent',
            LeadTimelineEntry.is_deleted.is_(False),
        )
        .order_by(LeadTimelineEntry.occurred_at.asc())
        .all()
    )
    rows: list[dict[str, Any]] = []
    for entry in entries:
        metadata = entry.event_metadata if isinstance(entry.event_metadata, dict) else {}
        campaign_id = metadata.get('campaign_id')
        olc_order_id = metadata.get('olc_order_id')
        template_name = metadata.get('template_name')
        creative = metadata.get('creative')
        label_parts = [p for p in (template_name, creative) if p]
        label = ', '.join(str(p) for p in label_parts) if label_parts else None
        if not label and olc_order_id:
            label = f'OLC order {olc_order_id}'
        if not label and campaign_id is not None:
            label = f'Campaign {campaign_id}'
        if not label:
            label = entry.summary or 'Mailer sent'
        rows.append({
            'id': f'timeline-{entry.id}',
            'sent_at': entry.occurred_at.isoformat() if entry.occurred_at else None,
            'label': label,
            'creative': creative,
            'template_name': template_name,
            'campaign_id': campaign_id,
            'olc_order_id': olc_order_id,
            'address_feedback': metadata.get('address_feedback'),
            'cancelled': bool(metadata.get('cancelled')),
            'source': 'timeline',
        })
    return rows


def _heal_mailer_history_gaps(lead: Any, healed_entries: list[dict[str, Any]]) -> None:
    """Append OLC dicts missing from ``lead.mailer_history`` and flag_modified.

    Mirrors the canonical JSONB-append pattern used by mail_campaign_service
    (``_stamp_address_feedback`` / ``_stamp_silent_omit``): read the current
    list, append plain dicts, reassign, then ``flag_modified``.
    """
    from sqlalchemy.orm.attributes import flag_modified

    raw = getattr(lead, 'mailer_history', None)
    if isinstance(raw, list):
        history = list(raw)
    elif raw:
        history = [raw]
    else:
        history = []
    for entry in healed_entries:
        history.append({
            k: v for k, v in entry.items()
            if v is not None
        })
    lead.mailer_history = history
    flag_modified(lead, 'mailer_history')


def consolidate_mailer_history(lead: Any, *, heal: bool = True) -> dict[str, Any]:
    """Union ``lead.mailer_history`` JSONB with ``mail_sent`` timeline rows.

    The OLC submit pipeline occasionally drops a campaign send from the
    ``mailer_history`` JSONB column (silent omit) while the ``mail_sent``
    LeadTimelineEntry still recorded it — see the 10305-class bug where a
    lead's import-string history undercounted mailers actually sent. This
    unions both sources, dedupes by any shared normalized OLC identifier
    (falling back to ``(sent_at, label)`` for legacy free-text rows),
    and — when ``heal`` is True — appends any timeline-only mailer as a plain
    OLC dict onto ``lead.mailer_history`` so future reads see it directly
    from the JSONB column without needing this union again.

    There is no separate mail-campaign/lead join table today (a
    ``MailCampaign`` only stores lead ids in JSON tracking columns), so the
    two sources unioned here — JSONB history and timeline ``mail_sent``
    entries — are the complete set of "easily available" sources.

    Returns the same shape as :func:`mailer_history_summary` plus
    ``healed_count`` (rows newly appended to the JSONB column this call).
    """
    jsonb_rows = normalize_mailer_history(getattr(lead, 'mailer_history', None))
    seen_keys: set[tuple[str, str | None, str | None]] = set()
    for row in jsonb_rows:
        seen_keys.update(_dedupe_keys(row))

    merged_rows = list(jsonb_rows)
    healed_entries: list[dict[str, Any]] = []
    for row in _timeline_mail_sent_rows(lead):
        keys = _dedupe_keys(row)
        if keys & seen_keys:
            continue
        seen_keys.update(keys)
        merged_rows.append(row)
        healed_entries.append({
            'sent_at': row.get('sent_at'),
            'template_name': row.get('template_name'),
            'creative': row.get('creative'),
            'campaign_id': row.get('campaign_id'),
            'olc_order_id': row.get('olc_order_id'),
            'address_feedback': row.get('address_feedback'),
            'cancelled': row.get('cancelled') or False,
        })

    if heal and healed_entries:
        _heal_mailer_history_gaps(lead, healed_entries)

    return {
        'count': len(merged_rows),
        'last_sent_at': _last_sent_from_rows(merged_rows),
        'rows': merged_rows,
        'healed_count': len(healed_entries),
    }
