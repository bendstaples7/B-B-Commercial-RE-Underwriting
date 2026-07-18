"""Capture and list past-owner snapshots for leads with stale or replaced contacts."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app import db
from app.models.lead_owner_snapshot import LeadOwnerSnapshot
from app.models.property_contact import PropertyContact
from app.services.scoring_rubric import (
    contacts_likely_prior_owner,
    effective_acquisition_date,
)

if TYPE_CHECKING:
    from app.models.lead import Lead

logger = logging.getLogger(__name__)

REASON_RECENT_SALE = 'recent_sale'
REASON_CONTACT_REPLACED = 'contact_replaced'


def build_owner_snapshot_payload(lead: Lead) -> dict:
    """Serialize current owner names, phones, emails, and mailing for storage."""
    from app.services.contact_service import ContactService

    contacts = ContactService().get_ordered_contacts_payload(lead.id)
    owner_names: list[dict] = []
    phones: list[dict] = []
    emails: list[dict] = []
    for c in contacts:
        role = c.get('role') or 'owner'
        if role not in ('owner', None):
            continue
        name = ' '.join(
            part for part in [(c.get('first_name') or '').strip(), (c.get('last_name') or '').strip()]
            if part
        )
        if name or role == 'owner':
            owner_names.append({
                'contact_id': c.get('id'),
                'first_name': c.get('first_name'),
                'last_name': c.get('last_name'),
                'role': c.get('role'),
                'is_primary': bool(c.get('is_primary')),
            })
        for p in c.get('phones') or []:
            phones.append({
                'value': p.get('value'),
                'label': p.get('label'),
                'confidence_score': p.get('confidence_score'),
            })
        for e in c.get('emails') or []:
            emails.append({'value': e.get('value'), 'label': e.get('label')})

    if not owner_names:
        o1 = ' '.join(
            part for part in [
                (getattr(lead, 'owner_first_name', None) or '').strip(),
                (getattr(lead, 'owner_last_name', None) or '').strip(),
            ] if part
        )
        o2 = ' '.join(
            part for part in [
                (getattr(lead, 'owner_2_first_name', None) or '').strip(),
                (getattr(lead, 'owner_2_last_name', None) or '').strip(),
            ] if part
        )
        if o1:
            owner_names.append({
                'contact_id': None,
                'first_name': lead.owner_first_name,
                'last_name': lead.owner_last_name,
                'role': 'owner',
                'is_primary': True,
            })
        if o2:
            owner_names.append({
                'contact_id': None,
                'first_name': lead.owner_2_first_name,
                'last_name': lead.owner_2_last_name,
                'role': 'owner',
                'is_primary': False,
            })
        if not phones:
            for i in range(1, 8):
                raw = getattr(lead, f'phone_{i}', None)
                if raw and str(raw).strip():
                    phones.append({'value': str(raw).strip(), 'label': None, 'confidence_score': None})
        if not emails:
            for i in range(1, 6):
                raw = getattr(lead, f'email_{i}', None)
                if raw and str(raw).strip():
                    emails.append({'value': str(raw).strip(), 'label': None})

    return {
        'owner_names': owner_names,
        'phones': phones,
        'emails': emails,
        'mailing_address': getattr(lead, 'mailing_address', None),
        'mailing_city': getattr(lead, 'mailing_city', None),
        'mailing_state': getattr(lead, 'mailing_state', None),
        'mailing_zip': getattr(lead, 'mailing_zip', None),
    }


def _payload_has_content(payload: dict) -> bool:
    if payload.get('owner_names'):
        return True
    if payload.get('phones') or payload.get('emails'):
        return True
    mailing = (
        (payload.get('mailing_address') or '').strip()
        or (payload.get('mailing_city') or '').strip()
        or (payload.get('mailing_state') or '').strip()
        or (payload.get('mailing_zip') or '').strip()
    )
    return bool(mailing)


def has_snapshot_for_sale(lead_id: int, sale_date) -> bool:
    """True when any snapshot already exists for this lead + sale date."""
    if sale_date is None:
        return False
    return (
        LeadOwnerSnapshot.query
        .filter_by(lead_id=lead_id, sale_date=sale_date)
        .first()
        is not None
    )


def _active_owners_already_superseded(lead_id: int) -> bool:
    """True when this property has former_owner links (post-replace history)."""
    return (
        PropertyContact.query
        .filter(
            PropertyContact.property_id == lead_id,
            PropertyContact.role == 'former_owner',
        )
        .first()
        is not None
    )


def capture_owner_snapshot(
    lead: Lead,
    *,
    reason: str,
    sale_date=None,
    commit: bool = False,
) -> LeadOwnerSnapshot | None:
    """Persist a snapshot of the lead's current owner/contact/mailing set."""
    if lead is None or getattr(lead, 'id', None) is None:
        return None

    payload = build_owner_snapshot_payload(lead)
    if not _payload_has_content(payload):
        return None

    if sale_date is None:
        sale_date = effective_acquisition_date(lead)

    # Idempotent recent_sale: one row per lead+sale (unique index enforces).
    if reason == REASON_RECENT_SALE and has_snapshot_for_sale(lead.id, sale_date):
        return None

    snap = LeadOwnerSnapshot(
        lead_id=lead.id,
        captured_at=datetime.now(timezone.utc),
        reason=reason,
        sale_date=sale_date,
        payload=payload,
    )
    from sqlalchemy.exc import IntegrityError
    try:
        with db.session.begin_nested():
            db.session.add(snap)
            db.session.flush()
    except IntegrityError:
        if reason == REASON_RECENT_SALE and has_snapshot_for_sale(lead.id, sale_date):
            return None
        raise

    if commit:
        db.session.commit()
    logger.info(
        'Captured owner snapshot lead_id=%s reason=%s sale_date=%s',
        lead.id, reason, sale_date,
    )
    return snap


def ensure_stale_owner_snapshot(lead: Lead, *, commit: bool = False) -> LeadOwnerSnapshot | None:
    """If contacts are stale for a sale and no snapshot exists yet, capture one.

    Skips when owners were already replaced (former_owner present) — those
    leads already have contact_replaced history and must not invent a
    recent_sale row of the *new* owner set.
    """
    if not contacts_likely_prior_owner(lead):
        return None
    sale = effective_acquisition_date(lead)
    if has_snapshot_for_sale(lead.id, sale):
        return None
    if _active_owners_already_superseded(lead.id):
        return None
    return capture_owner_snapshot(
        lead,
        reason=REASON_RECENT_SALE,
        sale_date=sale,
        commit=commit,
    )


def archive_active_owners_to_former(
    lead: Lead,
    *,
    reason: str = REASON_CONTACT_REPLACED,
    commit: bool = False,
) -> int:
    """Snapshot current owners, then re-role active owner links to former_owner.

    Returns the number of PropertyContact rows archived.
    """
    if lead is None or getattr(lead, 'id', None) is None:
        return 0

    capture_owner_snapshot(lead, reason=reason, commit=False)

    now = datetime.now(timezone.utc)
    links = (
        PropertyContact.query
        .filter(
            PropertyContact.property_id == lead.id,
            PropertyContact.role == 'owner',
        )
        .all()
    )
    archived = 0
    for link in links:
        link.role = 'former_owner'
        link.is_primary = False
        link.superseded_at = now
        archived += 1

    if commit:
        db.session.commit()
    else:
        db.session.flush()
    return archived


def list_past_owners_payload(lead_id: int) -> list[dict]:
    """Serialize snapshots newest-first for the command-center sidebar."""
    rows = (
        LeadOwnerSnapshot.query
        .filter_by(lead_id=lead_id)
        .order_by(LeadOwnerSnapshot.captured_at.desc(), LeadOwnerSnapshot.id.desc())
        .all()
    )
    out: list[dict] = []
    for row in rows:
        payload = row.payload if isinstance(row.payload, dict) else {}
        out.append({
            'id': row.id,
            'captured_at': row.captured_at.isoformat() if row.captured_at else None,
            'reason': row.reason,
            'sale_date': row.sale_date.isoformat() if row.sale_date else None,
            'owner_names': payload.get('owner_names') or [],
            'phones': payload.get('phones') or [],
            'emails': payload.get('emails') or [],
            'mailing_address': payload.get('mailing_address'),
            'mailing_city': payload.get('mailing_city'),
            'mailing_state': payload.get('mailing_state'),
            'mailing_zip': payload.get('mailing_zip'),
        })
    return out
