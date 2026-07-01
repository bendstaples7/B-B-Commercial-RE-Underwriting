"""Resolve the most recent physical-mail send date for leads."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import func, or_

from app import db
from app.models import Lead, MailQueueItem
from app.models.lead_timeline_entry import LeadTimelineEntry
from app.models.mail_campaign import MailCampaign
from app.services.lead_merge_utils import dedup_street_key, streets_match_normalized
from app.services.plugins.pin_utils import normalize_pin_for_socrata


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        if raw.endswith('Z'):
            raw = raw[:-1] + '+00:00'
        return _ensure_utc(datetime.fromisoformat(raw))
    except ValueError:
        return None


# Formats aligned with GoogleSheetsImporter._parse_date
_DATE_FORMATS = ('%Y-%m-%d', '%m/%d/%Y', '%m-%d-%Y', '%Y/%m/%d', '%m/%d/%y')
_US_DATE_RE = re.compile(r'\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b')
_ISO_DATE_RE = re.compile(r'\b(\d{4}-\d{2}-\d{2})\b')
_MAILER_DATE_KEYS = ('sent_at', 'last_sent', 'date')


def _parse_date_string(value) -> datetime | None:
    """Parse a date or datetime string; returns UTC midnight for date-only values."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return _ensure_utc(value)
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None

    iso_dt = _parse_iso_datetime(raw)
    if iso_dt:
        return iso_dt

    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(raw, fmt)
            return _ensure_utc(parsed)
        except ValueError:
            continue
    return None


def _dates_from_free_text(text: str) -> list[datetime]:
    """Extract all parseable dates from legacy spreadsheet free-text mailer_history."""
    candidates: list[datetime] = []

    whole = _parse_date_string(text)
    if whole:
        candidates.append(whole)

    for match in _US_DATE_RE.finditer(text):
        candidates.append(_parse_date_string(match.group(0)))

    for match in _ISO_DATE_RE.finditer(text):
        candidates.append(_parse_date_string(match.group(0)))

    return [dt for dt in candidates if dt is not None]


def _dates_from_mailer_entry(entry) -> list[datetime]:
    if isinstance(entry, str):
        return _dates_from_free_text(entry)
    if isinstance(entry, dict):
        found: list[datetime] = []
        for key in _MAILER_DATE_KEYS:
            dt = _parse_date_string(entry.get(key))
            if dt:
                found.append(dt)
        return found
    return []


def last_mailed_from_mailer_history(mailer_history) -> datetime | None:
    """Best-effort parse of legacy or OLC mailer_history JSON."""
    if mailer_history is None:
        return None

    candidates: list[datetime] = []

    if isinstance(mailer_history, str):
        candidates.extend(_dates_from_free_text(mailer_history))
    elif isinstance(mailer_history, list):
        for entry in mailer_history:
            candidates.extend(_dates_from_mailer_entry(entry))
    elif isinstance(mailer_history, dict):
        candidates.extend(_dates_from_mailer_entry(mailer_history))

    return max(candidates) if candidates else None


def _pick_latest(current: datetime | None, candidate: datetime | None) -> datetime | None:
    if candidate is None:
        return current
    if current is None:
        return _ensure_utc(candidate)
    return max(_ensure_utc(current), _ensure_utc(candidate))


def _pin_digits_sql():
    return func.replace(
        func.replace(func.coalesce(Lead.county_assessor_pin, ''), '-', ''),
        ' ',
        '',
    )


def _owner_address_key(lead: Lead) -> tuple | None:
    street_key = dedup_street_key(lead.property_street)
    first = (lead.owner_first_name or '').strip().lower()
    last = (lead.owner_last_name or '').strip().lower()
    if not street_key or not first or not last:
        return None
    return (lead.owner_user_id, first, last, street_key)


def _sibling_mailer_history_dates(leads: list[Lead]) -> dict[int, datetime | None]:
    """Max mailer_history date per lead, including sibling PIN/address matches."""
    if not leads:
        return {}

    pin_digits: set[str] = set()
    owner_keys: set[tuple] = set()
    lead_pin: dict[int, str] = {}
    lead_addr: dict[int, tuple] = {}

    for lead in leads:
        if lead.county_assessor_pin:
            digits = normalize_pin_for_socrata(lead.county_assessor_pin)
            if digits:
                pin_digits.add(digits)
                lead_pin[lead.id] = digits
        addr_key = _owner_address_key(lead)
        if addr_key:
            owner_keys.add(addr_key)
            lead_addr[lead.id] = addr_key

    owner_user_ids = {lead.owner_user_id for lead in leads if lead.owner_user_id}
    has_null_owner = any(lead.owner_user_id is None for lead in leads)

    sibling_leads: dict[int, Lead] = {lead.id: lead for lead in leads}
    if pin_digits:
        pin_clauses = [_pin_digits_sql() == pd for pd in pin_digits]
        q = Lead.query.filter(or_(*pin_clauses))
        if owner_user_ids:
            q = q.filter(Lead.owner_user_id.in_(owner_user_ids))
        elif has_null_owner:
            q = q.filter(Lead.owner_user_id.is_(None))
        for row in q.all():
            sibling_leads[row.id] = row

    for owner_user_id, first, last, _street_key in owner_keys:
        q = Lead.query.filter(
            func.lower(func.trim(Lead.owner_first_name)) == first,
            func.lower(func.trim(Lead.owner_last_name)) == last,
            Lead.owner_user_id == owner_user_id,
        )
        for row in q.all():
            sibling_leads[row.id] = row

    pin_group_dates: dict[str, datetime | None] = {}
    for row in sibling_leads.values():
        history_dt = last_mailed_from_mailer_history(row.mailer_history)
        if row.county_assessor_pin:
            digits = normalize_pin_for_socrata(row.county_assessor_pin)
            if digits:
                pin_group_dates[digits] = _pick_latest(pin_group_dates.get(digits), history_dt)

    addr_group_dates: dict[tuple, datetime | None] = {}
    for key in owner_keys:
        group_date: datetime | None = None
        owner_user_id, first, last, street_key = key
        rep_street = next(
            (lead.property_street for lead in leads if _owner_address_key(lead) == key),
            None,
        )
        for row in sibling_leads.values():
            row_key = _owner_address_key(row)
            if not row_key:
                continue
            if row_key[0] != owner_user_id or row_key[1] != first or row_key[2] != last:
                continue
            same_building = row_key[3] == street_key
            if not same_building and rep_street:
                same_building = streets_match_normalized(rep_street, row.property_street)
            if not same_building:
                continue
            group_date = _pick_latest(group_date, last_mailed_from_mailer_history(row.mailer_history))
        addr_group_dates[key] = group_date

    result: dict[int, datetime | None] = {}
    for lead in leads:
        candidate: datetime | None = None
        if lead.id in lead_pin:
            candidate = _pick_latest(candidate, pin_group_dates.get(lead_pin[lead.id]))
        if lead.id in lead_addr:
            candidate = _pick_latest(candidate, addr_group_dates.get(lead_addr[lead.id]))
        result[lead.id] = candidate
    return result


def get_last_mailed_at_by_lead_ids(lead_ids: list[int]) -> dict[int, datetime | None]:
    """Return the latest known mail send date per lead id."""
    if not lead_ids:
        return {}

    result: dict[int, datetime | None] = {lead_id: None for lead_id in lead_ids}

    timeline_rows = (
        db.session.query(
            LeadTimelineEntry.lead_id,
            func.max(LeadTimelineEntry.occurred_at),
        )
        .filter(
            LeadTimelineEntry.lead_id.in_(lead_ids),
            LeadTimelineEntry.event_type == 'mail_sent',
            LeadTimelineEntry.is_deleted.is_(False),
        )
        .group_by(LeadTimelineEntry.lead_id)
        .all()
    )
    for lead_id, occurred_at in timeline_rows:
        result[lead_id] = _pick_latest(result[lead_id], occurred_at)

    campaign_rows = (
        db.session.query(
            MailQueueItem.lead_id,
            func.max(MailCampaign.submitted_at),
        )
        .join(MailCampaign, MailQueueItem.campaign_id == MailCampaign.id)
        .filter(
            MailQueueItem.lead_id.in_(lead_ids),
            MailQueueItem.status == 'sent',
            MailCampaign.submitted_at.isnot(None),
        )
        .group_by(MailQueueItem.lead_id)
        .all()
    )
    for lead_id, submitted_at in campaign_rows:
        result[lead_id] = _pick_latest(result[lead_id], submitted_at)

    leads = Lead.query.filter(Lead.id.in_(lead_ids)).all()
    for lead in leads:
        history_dt = last_mailed_from_mailer_history(lead.mailer_history)
        result[lead.id] = _pick_latest(result[lead.id], history_dt)

    sibling_dates = _sibling_mailer_history_dates(leads)
    for lead_id, sibling_dt in sibling_dates.items():
        result[lead_id] = _pick_latest(result.get(lead_id), sibling_dt)

    return result


def format_last_mailed_at(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return _ensure_utc(dt).isoformat()
