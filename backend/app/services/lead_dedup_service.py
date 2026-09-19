"""Lead deduplication service — identity lookup, merge, and duplicate sentinel."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import and_, func, or_
from sqlalchemy.exc import IntegrityError

from app import db
from app.models.hubspot_match import HubSpotMatch
from app.models.lead import Lead, LeadAuditTrail
from app.services.lead_merge_utils import (
    dedup_street_key,
    legacy_glued_house_range_key,
    merge_mailer_history,
    pick_merge_winner,
    streets_match_duplicate_merge,
    streets_match_normalized,
    streets_match_same_situs,
    winner_sort_key,
)
from app.services.plugins.pin_utils import normalize_pin_for_socrata

logger = logging.getLogger(__name__)

COPYABLE_FIELDS = [
    'phone_1', 'phone_2', 'phone_3', 'phone_4', 'phone_5', 'phone_6', 'phone_7',
    'email_1', 'email_2', 'email_3', 'email_4', 'email_5',
    'mailing_address', 'mailing_city', 'mailing_state', 'mailing_zip',
    'notes', 'source', 'date_identified',
    'needs_skip_trace', 'skip_tracer', 'date_skip_traced',
    'date_added_to_hubspot', 'county_assessor_pin',
    'ownership_type', 'acquisition_date',
    'bedrooms', 'bathrooms', 'square_footage', 'lot_size', 'year_built',
    'units', 'units_allowed', 'zoning',
    'asking_price',
    'most_recent_sale', 'owner_2_first_name', 'owner_2_last_name',
    'address_2', 'returned_addresses', 'up_next_to_mail', 'mailer_history',
    'lead_score', 'lead_category', 'property_type',
]

FK_REPOINTS = [
    ('lead_audit_trail', 'lead_id'),
    ('lead_tasks', 'lead_id'),
    ('lead_timeline_entries', 'lead_id'),
    ('lead_scores', 'lead_id'),
    ('lead_owner_snapshots', 'lead_id'),
    ('enrichment_records', 'lead_id'),
    ('hubspot_signals', 'lead_id'),
    ('lead_deal_links', 'lead_id'),
    ('marketing_list_members', 'lead_id'),
    ('property_contacts', 'property_id'),
    ('property_organization_links', 'property_id'),
    ('owner_organization_links', 'owner_id'),
    ('tasks', 'lead_id'),
    ('mail_queue_items', 'lead_id'),
    ('motivation_signals', 'lead_id'),
]


def refresh_lead_dedup_fields(lead: Lead) -> None:
    """Recompute persisted dedup column from current property_street."""
    key = dedup_street_key(lead.property_street)
    lead.normalized_street = key or None


def _dedup_index_conflict_exists(
    *,
    lead: Lead,
    proposed_street: str,
    ignore_ids: set[int],
) -> bool:
    """True when a street update would collide with the owner+street index."""
    key = dedup_street_key(proposed_street)
    owner_user_id = getattr(lead, 'owner_user_id', None)
    first = (getattr(lead, 'owner_first_name', None) or '').strip()
    last = (getattr(lead, 'owner_last_name', None) or '').strip()
    if not (key and owner_user_id and first and last):
        return False
    query = Lead.query.filter(
        Lead.owner_user_id == owner_user_id,
        func.lower(func.trim(Lead.owner_first_name)) == first.lower(),
        func.lower(func.trim(Lead.owner_last_name)) == last.lower(),
        Lead.normalized_street == key,
    )
    if ignore_ids:
        query = query.filter(~Lead.id.in_(ignore_ids))
    return db.session.query(query.exists()).scalar()


def _assessor_pin_conflict_exists(
    *,
    lead: Lead,
    proposed_pin: Any,
    ignore_ids: set[int],
) -> bool:
    """True when a PIN write would hit uq_leads_owner_assessor_pin."""
    pin = '' if proposed_pin is None else str(proposed_pin).strip()
    owner_user_id = getattr(lead, 'owner_user_id', None)
    if not (pin and owner_user_id):
        return False
    query = Lead.query.filter(
        Lead.owner_user_id == owner_user_id,
        Lead.county_assessor_pin == pin,
    )
    if ignore_ids:
        query = query.filter(~Lead.id.in_(ignore_ids))
    return bool(db.session.query(query.exists()).scalar())


def _vacate_loser_dedup_keys(loser: Lead) -> None:
    """Release unique-index keys on the row that is about to be deleted.

    Postgres checks ``uq_leads_owner_normalized_street`` and
    ``uq_leads_owner_assessor_pin`` on each UPDATE. Copying the PIN, or
    aligning the owner and street, fails while this row still holds those
    keys. ``normalized_street`` is cleared without touching
    ``property_street`` so the before-update listener does not recompute it.
    """
    changed = False
    if (getattr(loser, 'county_assessor_pin', None) or '').strip():
        loser.county_assessor_pin = None
        changed = True
    if (getattr(loser, 'normalized_street', None) or '').strip():
        loser.normalized_street = None
        changed = True
    if changed:
        db.session.flush()


def _street_prefilter(query, street: str):
    """Bound owner-name scans with a coarse building-level SQL predicate."""
    key = dedup_street_key(street)
    if not key:
        return query
    house_token = key.split(' ', 1)[0]
    normalized_prefix = f'{key} %'
    return query.filter(or_(
        Lead.normalized_street == key,
        Lead.normalized_street.ilike(normalized_prefix),
        Lead.property_street.ilike(f'{house_token}%'),
    ))


def _owner_name_filters(
    query,
    owner_first: Optional[str],
    owner_last: Optional[str],
):
    first = (owner_first or '').strip()
    last = (owner_last or '').strip()
    if first:
        query = query.filter(func.lower(func.trim(Lead.owner_first_name)) == first.lower())
    if last:
        query = query.filter(func.lower(func.trim(Lead.owner_last_name)) == last.lower())
    return query


def _pin_digits_sql():
    return func.replace(
        func.replace(func.coalesce(Lead.county_assessor_pin, ''), '-', ''),
        ' ',
        '',
    )


def find_lead_by_identity(
    *,
    owner_user_id: Optional[str] = None,
    owner_first_name: Optional[str] = None,
    owner_last_name: Optional[str] = None,
    property_street: Optional[str] = None,
    county_assessor_pin: Optional[str] = None,
) -> Optional[Lead]:
    """Find an existing lead by PIN or owner + building-level street identity."""
    pin = (county_assessor_pin or '').strip()
    if pin:
        pin_digits = normalize_pin_for_socrata(pin)
        if pin_digits:
            q = Lead.query.filter(_pin_digits_sql() == pin_digits)
            if owner_user_id:
                q = q.filter(Lead.owner_user_id == owner_user_id)
            hit = q.first()
            if hit:
                return hit

    street_key = dedup_street_key(property_street)
    first = (owner_first_name or '').strip()
    last = (owner_last_name or '').strip()
    if not street_key or not first or not last:
        return None

    q = Lead.query.filter(Lead.normalized_street == street_key)
    q = _owner_name_filters(q, first, last)
    if owner_user_id:
        q = q.filter(Lead.owner_user_id == owner_user_id)
    hit = q.first()
    if hit:
        return hit

    # Fallback when normalized_street not yet backfilled on older rows.
    q = Lead.query.filter(Lead.property_street.isnot(None))
    q = _owner_name_filters(q, first, last)
    if owner_user_id:
        q = q.filter(Lead.owner_user_id == owner_user_id)
    for candidate in q:
        if streets_match_normalized(property_street, candidate.property_street):
            refresh_lead_dedup_fields(candidate)
            return candidate
    return None


def confirmed_hubspot_lead_ids() -> set[int]:
    rows = HubSpotMatch.query.filter(
        HubSpotMatch.internal_record_type == 'lead',
        HubSpotMatch.status == 'confirmed',
        HubSpotMatch.internal_record_id.isnot(None),
    ).all()
    return {int(r.internal_record_id) for r in rows}


def _lead_to_merge_record(lead: Lead) -> dict[str, Any]:
    return {
        'id': lead.id,
        'property_street': lead.property_street,
        'owner_first_name': lead.owner_first_name,
        'owner_last_name': lead.owner_last_name,
        'owner_user_id': lead.owner_user_id,
        'lead_status': lead.lead_status,
        'has_phone': lead.has_phone,
        'has_email': lead.has_email,
        'last_hubspot_sync_at': lead.last_hubspot_sync_at,
        'county_assessor_pin': getattr(lead, 'county_assessor_pin', None),
    }


def merge_confidence(
    records: list[dict[str, Any]],
    confirmed_ids: set[int],
) -> str:
    """Return 'clear' when auto-merge is safe, else 'ambiguous'."""
    if len(records) < 2:
        return 'clear'
    confirmed_in_cluster = [r for r in records if r['id'] in confirmed_ids]
    if len(confirmed_in_cluster) > 1:
        return 'ambiguous'
    winner = pick_merge_winner(records, confirmed_ids)
    winner_core = winner_sort_key(winner, confirmed_ids)[:4]
    for record in records:
        if record['id'] == winner['id']:
            continue
        if winner_sort_key(record, confirmed_ids)[:4] == winner_core:
            return 'ambiguous'
    return 'clear'


def _repoint_hubspot_matches(winner_id: int, loser_id: int) -> None:
    loser_matches = HubSpotMatch.query.filter(
        HubSpotMatch.internal_record_type == 'lead',
        HubSpotMatch.internal_record_id == loser_id,
    ).all()
    for hm in loser_matches:
        existing = HubSpotMatch.query.filter(
            HubSpotMatch.hubspot_record_type == hm.hubspot_record_type,
            HubSpotMatch.hubspot_id == hm.hubspot_id,
            HubSpotMatch.internal_record_id == winner_id,
        ).first()
        if existing:
            db.session.delete(hm)
        else:
            hm.internal_record_id = winner_id


def _prefer_newer_sale_onto_winner(winner: Lead, loser: Lead) -> None:
    """When duplicates disagree on sale date, keep the newer transfer."""
    from app.services.scoring_rubric import effective_acquisition_date

    w_sale = effective_acquisition_date(winner)
    l_sale = effective_acquisition_date(loser)
    if l_sale is None:
        return
    if w_sale is not None and l_sale <= w_sale:
        return
    if getattr(loser, 'most_recent_sale', None) not in (None, ''):
        winner.most_recent_sale = loser.most_recent_sale
    if getattr(loser, 'most_recent_sale_price', None) not in (None, ''):
        winner.most_recent_sale_price = loser.most_recent_sale_price
    loser_acq = getattr(loser, 'acquisition_date', None)
    if loser_acq is not None:
        winner_acq = getattr(winner, 'acquisition_date', None)
        if winner_acq is None or loser_acq > winner_acq:
            winner.acquisition_date = loser_acq
    elif l_sale is not None:
        # Loser won via parsed most_recent_sale string only — keep flat date in sync.
        winner_acq = getattr(winner, 'acquisition_date', None)
        if winner_acq is None or l_sale > winner_acq:
            winner.acquisition_date = l_sale


def _owner_name_street_conflict(
    lead: Lead,
    first_name: str | None,
    last_name: str | None,
) -> bool:
    """True when rewriting primary owner would hit uq_leads_owner_normalized_street."""
    key = getattr(lead, 'normalized_street', None) or dedup_street_key(
        getattr(lead, 'property_street', None),
    )
    owner_user_id = getattr(lead, 'owner_user_id', None)
    first = (first_name or '').strip()
    last = (last_name or '').strip()
    if not (key and owner_user_id and first and last):
        return False
    ignore = {lead.id} if isinstance(lead.id, int) else set()
    query = Lead.query.filter(
        Lead.owner_user_id == owner_user_id,
        func.lower(func.trim(Lead.owner_first_name)) == first.lower(),
        func.lower(func.trim(Lead.owner_last_name)) == last.lower(),
        Lead.normalized_street == key,
    )
    if ignore:
        query = query.filter(~Lead.id.in_(ignore))
    return bool(db.session.query(query.exists()).scalar())


def _merge_flat_owner_people(winner: Lead, loser: Lead) -> None:
    """Union flat owners from both sides; split joint names like ``A and B``.

    Never renames primary when that would collide with the owner+street unique
    index — fills empty ``owner_2_*`` instead so co-owners are not silently lost.
    """
    from app.services.plugins.owner_name_utils import (
        apply_joint_owner_split_to_lead_flats,
        collect_flat_owner_people,
        owner_names_equivalent,
    )

    people: list[tuple[str | None, str | None]] = []
    for source in (winner, loser):
        for person in collect_flat_owner_people(source):
            duplicate = False
            for existing in people:
                if owner_names_equivalent(
                    person[0], person[1], existing[0], existing[1],
                ):
                    duplicate = True
                    break
            if not duplicate:
                people.append(person)

    if not people:
        apply_joint_owner_split_to_lead_flats(winner)
        return

    primary = people[0]
    can_rewrite_primary = not _owner_name_street_conflict(
        winner, primary[0], primary[1],
    )
    if can_rewrite_primary:
        winner.owner_first_name = primary[0]
        winner.owner_last_name = primary[1]
        secondary_candidates = people[1:]
    else:
        logger.info(
            'merge keeping primary owner flats on winner=%s; rename would collide',
            getattr(winner, 'id', None),
        )
        secondary_candidates = [
            person for person in people
            if not owner_names_equivalent(
                person[0], person[1],
                winner.owner_first_name, winner.owner_last_name,
            )
        ]

    if secondary_candidates:
        second = secondary_candidates[0]
        o2_empty = not (
            (getattr(winner, 'owner_2_first_name', None) or '').strip()
            or (getattr(winner, 'owner_2_last_name', None) or '').strip()
        )
        if o2_empty or owner_names_equivalent(
            getattr(winner, 'owner_2_first_name', None),
            getattr(winner, 'owner_2_last_name', None),
            second[0],
            second[1],
        ):
            winner.owner_2_first_name = second[0]
            winner.owner_2_last_name = second[1]
    elif can_rewrite_primary:
        apply_joint_owner_split_to_lead_flats(winner)


def _prefer_cleaner_property_street(winner: Lead, loser: Lead) -> None:
    """Prefer cleaner / more specific street when both normalize to one building."""
    w_street = (winner.property_street or '').strip()
    l_street = (loser.property_street or '').strip()
    if not l_street or not streets_match_normalized(w_street, l_street):
        return
    # Glued ZIP-only suffixes (e.g. "3052 N Davlin 60618") are noisier than
    # "3052 N Davlin Ct 1" — prefer the side without a trailing 5-digit ZIP.
    import re
    zip_suffix = re.compile(r'\s+\d{5}(?:-\d{4})?\s*$')
    w_has_zip = bool(zip_suffix.search(w_street))
    l_has_zip = bool(zip_suffix.search(l_street))
    preferred: str | None = None
    if w_has_zip and not l_has_zip:
        preferred = l_street
    elif not w_has_zip and not l_has_zip:
        # Prefer unit-bearing / longer line (bare husk vs "… Ave 1r").
        w_u = w_street.upper()
        l_u = l_street.upper()
        if l_u.startswith(w_u + ' ') or (
            len(l_street) > len(w_street)
            and dedup_street_key(w_street) == dedup_street_key(l_street)
        ):
            preferred = l_street
    if preferred:
        ignore_ids = {winner.id} if isinstance(winner.id, int) else set()
        if isinstance(loser.id, int):
            ignore_ids.add(loser.id)
        if _dedup_index_conflict_exists(
            lead=winner,
            proposed_street=preferred,
            ignore_ids=ignore_ids,
        ):
            logger.info(
                'skipping cleaner street preference for winner=%s; normalized street would collide',
                winner.id,
            )
            return
        winner.property_street = preferred
        refresh_lead_dedup_fields(winner)
        # Address completion runs once at merge level — avoid double GIS here.


_MERGE_STATUS_VALUES = frozenset({
    'skip_trace',
    'awaiting_skip_trace',
    'mailing_no_contact_made',
    'mailing_contacted_no_interest',
    'mailing_contacted_interested',
    'negotiating_remote',
    'in_person_appointment',
    'offer_delivered',
    'deprioritize',
    'deal_won',
    'deal_lost',
    'suppressed',
    'do_not_contact',
})

_MERGE_TEXT_LIMITS = {
    'property_street': 500,
    'property_city': 100,
    'property_state': 50,
    'property_zip': 20,
    'county_assessor_pin': 50,
    'property_type': 50,
    'source': 100,
    'deal_source': 255,
    'data_source': 100,
}


def _clip_choice(value: Any, limit: int) -> str | None:
    text = '' if value is None else str(value).strip()
    if not text:
        return None
    return text[:limit]


def _split_person_name(name: str) -> tuple[str, str]:
    parts = [part for part in str(name or '').replace(',', ' ').split() if part]
    if not parts:
        return '', ''
    if len(parts) == 1:
        return parts[0][:128], ''
    return parts[0][:128], ' '.join(parts[1:])[:128]


def _delete_lead_rows(table_name: str, column: str, lead_id: int) -> None:
    table = db.metadata.tables.get(table_name)
    if table is None or column not in table.c:
        return
    db.session.execute(table.delete().where(table.c[column] == lead_id))


def _drop_unchecked_merge_rows(
    lead_id: int,
    *,
    drop_timeline: bool,
    drop_tasks: bool,
    drop_contacts: bool,
    drop_orgs: bool,
) -> None:
    if drop_timeline:
        _delete_lead_rows('lead_timeline_entries', 'lead_id', lead_id)
    if drop_tasks:
        _delete_lead_rows('lead_tasks', 'lead_id', lead_id)
        _delete_lead_rows('tasks', 'lead_id', lead_id)
    if drop_contacts:
        _delete_lead_rows('property_contacts', 'property_id', lead_id)
    if drop_orgs:
        _delete_lead_rows('property_organization_links', 'property_id', lead_id)


def _choice_flag(choices: dict[str, Any] | None, key: str, default: bool = True) -> bool:
    if not isinstance(choices, dict) or key not in choices:
        return default
    return bool(choices.get(key))


def _write_contact_slots(winner: Lead, values: list[Any], prefix: str, count: int) -> bool:
    """Replace flat phone_1.. or email_1.. with the dialog's chosen list."""
    from app.services.phone_confidence_service import PhoneConfidenceService

    cleaned: list[str] = []
    seen: set[str] = set()
    limit = 255 if prefix == 'email' else 80
    for raw in values:
        text = str(raw or '').strip()
        if not text:
            continue
        if prefix == 'phone':
            key = PhoneConfidenceService.normalize_phone(text) or text.lower()
        else:
            key = text.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        cleaned.append(text[:limit])
        if len(cleaned) >= count:
            break
    for index in range(1, count + 1):
        setattr(winner, f'{prefix}_{index}', cleaned[index - 1] if index <= len(cleaned) else None)
    return bool(cleaned)


def _contact_name_key(contact: Any) -> str:
    return _person_name_key(' '.join(
        part
        for part in [
            str(getattr(contact, 'first_name', '') or '').strip(),
            str(getattr(contact, 'last_name', '') or '').strip(),
        ]
        if part
    ))


def _person_name_key(name: Any) -> str:
    return ' '.join(str(name or '').strip().lower().split())


def _filter_owner_contacts_to_people(lead_id: int, names: list[Any]) -> None:
    """Remove owner links that are not in the dialog's explicit People result."""
    from app.models.property_contact import PropertyContact

    selected = {
        _person_name_key(name)
        for name in names
        if _person_name_key(name)
    }
    for link in PropertyContact.query.filter_by(property_id=lead_id, role='owner').all():
        if _contact_name_key(link.contact) not in selected:
            db.session.delete(link)


def _phone_choice_keys(values: list[Any]) -> set[str]:
    from app.services.phone_confidence_service import PhoneConfidenceService

    keys: set[str] = set()
    for value in values:
        text = str(value or '').strip()
        if not text:
            continue
        key = PhoneConfidenceService.normalize_phone(text) or text.lower()
        if key:
            keys.add(key)
    return keys


def _email_choice_keys(values: list[Any]) -> set[str]:
    return {
        str(value or '').strip().lower()
        for value in values
        if str(value or '').strip()
    }


def _filter_owner_contact_methods(
    lead_id: int,
    *,
    phones: list[Any] | None,
    emails: list[Any] | None,
) -> None:
    """Apply dialog contact-method selections to relational owner contacts."""
    if phones is None and emails is None:
        return
    from app.models.contact import Contact
    from app.models.contact_email import ContactEmail
    from app.models.contact_phone import ContactPhone
    from app.models.property_contact import PropertyContact
    from app.services.phone_confidence_service import PhoneConfidenceService

    owner_links = PropertyContact.query.filter_by(property_id=lead_id, role='owner').all()
    owner_contact_ids: list[int] = []
    for link in owner_links:
        shared_elsewhere = PropertyContact.query.filter(
            PropertyContact.contact_id == link.contact_id,
            PropertyContact.property_id != lead_id,
        ).first()
        if shared_elsewhere is not None:
            original = link.contact
            clone = Contact(
                first_name=original.first_name,
                last_name=original.last_name,
                role=original.role,
                role_description=original.role_description,
                notes=original.notes,
                name_locked=original.name_locked,
                keep_on_gis=original.keep_on_gis,
            )
            db.session.add(clone)
            db.session.flush()
            for phone in original.phones or []:
                db.session.add(ContactPhone(
                    contact_id=clone.id,
                    value=phone.value,
                    label=phone.label,
                    notes=phone.notes,
                    confidence_score=phone.confidence_score,
                    last_outcome=phone.last_outcome,
                    last_called_at=phone.last_called_at,
                    source=phone.source,
                ))
            for email in original.emails or []:
                db.session.add(ContactEmail(
                    contact_id=clone.id,
                    value=email.value,
                    label=email.label,
                ))
            link.contact_id = clone.id
            owner_contact_ids.append(clone.id)
        else:
            owner_contact_ids.append(link.contact_id)
    if not owner_contact_ids:
        return
    if phones is not None:
        keep_phones = _phone_choice_keys(phones)
        for row in ContactPhone.query.filter(ContactPhone.contact_id.in_(owner_contact_ids)).all():
            key = PhoneConfidenceService.normalize_phone(row.value) or str(row.value or '').strip().lower()
            if key not in keep_phones:
                db.session.delete(row)
    if emails is not None:
        keep_emails = _email_choice_keys(emails)
        for row in ContactEmail.query.filter(ContactEmail.contact_id.in_(owner_contact_ids)).all():
            if str(row.value or '').strip().lower() not in keep_emails:
                db.session.delete(row)


def apply_merge_field_choices(
    winner: Lead,
    choices: dict[str, Any] | None,
    *,
    ignore_conflict_ids: set[int] | None = None,
) -> None:
    """Write the dialog's After combine edits onto the surviving lead.

    Score is not written here — the caller rescores. Missing keys keep whatever
    the structural merge already copied.
    """
    if not isinstance(choices, dict):
        return
    names = choices.get('people_names')
    if isinstance(names, list):
        cleaned = [str(name).strip() for name in names if str(name).strip()]
        first, last = _split_person_name(cleaned[0]) if cleaned else ('', '')
        if cleaned and _owner_name_street_conflict(winner, first, last):
            logger.info(
                'keeping winner=%s owner name; selected name would collide',
                winner.id,
            )
        else:
            winner.owner_first_name = None
            winner.owner_last_name = None
            winner.owner_2_first_name = None
            winner.owner_2_last_name = None
            if cleaned:
                winner.owner_first_name = first or None
                winner.owner_last_name = last or None
                if len(cleaned) > 1:
                    second_first, second_last = _split_person_name(cleaned[1])
                    winner.owner_2_first_name = second_first or None
                    winner.owner_2_last_name = second_last or None
    for field, limit in _MERGE_TEXT_LIMITS.items():
        if field not in choices:
            continue
        if field == 'property_type' and bool(getattr(winner, 'lead_category_locked', False)):
            continue
        if field == 'property_street':
            proposed_street = _clip_choice(choices.get(field), limit)
            if proposed_street and _dedup_index_conflict_exists(
                lead=winner,
                proposed_street=proposed_street,
                ignore_ids=ignore_conflict_ids or set(),
            ):
                logger.info(
                    'skipping merge-choice street for winner=%s; normalized street would collide',
                    winner.id,
                )
                continue
            setattr(winner, field, proposed_street)
            continue
        if field == 'county_assessor_pin':
            proposed_pin = _clip_choice(choices.get(field), limit)
            if proposed_pin and _assessor_pin_conflict_exists(
                lead=winner,
                proposed_pin=proposed_pin,
                ignore_ids=ignore_conflict_ids or set(),
            ):
                logger.info(
                    'skipping merge-choice PIN for winner=%s; PIN would collide',
                    winner.id,
                )
                continue
            setattr(winner, field, proposed_pin)
            continue
        setattr(winner, field, _clip_choice(choices.get(field), limit))
    if 'units' in choices:
        raw = choices.get('units')
        if raw in (None, ''):
            winner.units = None
        else:
            try:
                winner.units = int(raw)
            except (TypeError, ValueError):
                pass
    status = choices.get('lead_status')
    if isinstance(status, str) and status in _MERGE_STATUS_VALUES:
        winner.lead_status = status
    if isinstance(choices.get('phones'), list):
        winner.has_phone = _write_contact_slots(winner, choices['phones'], 'phone', 7)
    if isinstance(choices.get('emails'), list):
        winner.has_email = _write_contact_slots(winner, choices['emails'], 'email', 5)
    if getattr(winner, 'property_street', None):
        refresh_lead_dedup_fields(winner)


def merge_lead_into_winner(
    winner: Lead,
    loser: Lead,
    *,
    changed_by: str = 'dedup_sentinel',
    choices: dict[str, Any] | None = None,
) -> None:
    """Merge loser into winner (ORM). Caller must commit."""
    winner_id = winner.id
    loser_id = loser.id
    # Snapshot before vacating — the copy loop still needs the loser's PIN.
    loser_pin = getattr(loser, 'county_assessor_pin', None)
    _vacate_loser_dedup_keys(loser)
    explicit_choices = isinstance(choices, dict)
    explicit_people_names = choices.get('people_names') if explicit_choices else None
    if isinstance(choices, dict):
        _drop_unchecked_merge_rows(
            loser_id,
            drop_timeline=not _choice_flag(choices, 'keep_incoming_activities'),
            drop_tasks=not _choice_flag(choices, 'keep_incoming_activities'),
            drop_contacts=not _choice_flag(choices, 'keep_incoming_people'),
            drop_orgs=not _choice_flag(choices, 'keep_incoming_companies'),
        )
        _drop_unchecked_merge_rows(
            winner_id,
            drop_timeline=not _choice_flag(choices, 'keep_primary_activities'),
            drop_tasks=not _choice_flag(choices, 'keep_primary_activities'),
            drop_contacts=not _choice_flag(choices, 'keep_primary_people'),
            drop_orgs=not _choice_flag(choices, 'keep_primary_companies'),
        )

    for table_name, col_name in FK_REPOINTS:
        table = db.metadata.tables[table_name]
        rows = db.session.execute(
            db.select(table.c.id).where(table.c[col_name] == loser_id)
        ).fetchall()
        for (row_id,) in rows:
            try:
                with db.session.begin_nested():
                    db.session.execute(
                        table.update().where(table.c.id == row_id).values({col_name: winner_id})
                    )
            except IntegrityError:
                db.session.execute(table.delete().where(table.c.id == row_id))

    _repoint_hubspot_matches(winner_id, loser_id)

    for field in COPYABLE_FIELDS:
        if field == 'mailer_history':
            merged = merge_mailer_history(winner.mailer_history, loser.mailer_history)
            if merged is not None:
                winner.mailer_history = merged
            continue
        w_val = getattr(winner, field, None)
        l_val = getattr(loser, field, None)
        if field == 'county_assessor_pin':
            l_val = loser_pin
        if field == 'lead_score':
            # Scoring has a single writer — caller must rescore after commit.
            continue
        if field in ('most_recent_sale', 'acquisition_date', 'most_recent_sale_price'):
            # Handled below — prefer the newer transfer, not "winner empty only".
            continue
        if field in ('lead_category', 'property_type') and bool(
            getattr(winner, 'lead_category_locked', False)
        ):
            # Locked Residential/Commercial must not pick up loser CoStar/type fills.
            continue
        if (w_val is None or w_val == '') and l_val not in (None, ''):
            if field == 'county_assessor_pin' and _assessor_pin_conflict_exists(
                lead=winner,
                proposed_pin=l_val,
                ignore_ids={winner_id, loser_id},
            ):
                logger.info(
                    'skipping copied PIN for winner=%s; PIN would collide',
                    winner_id,
                )
                continue
            setattr(winner, field, l_val)

    for field in ('property_city', 'property_state', 'property_zip'):
        w_val = getattr(winner, field, None)
        l_val = getattr(loser, field, None)
        if not (str(w_val).strip() if w_val is not None else '') and (
            str(l_val).strip() if l_val is not None else ''
        ):
            setattr(winner, field, l_val)

    _prefer_newer_sale_onto_winner(winner, loser)
    _prefer_cleaner_property_street(winner, loser)
    apply_merge_field_choices(
        winner,
        choices,
        ignore_conflict_ids={winner_id, loser_id},
    )
    if isinstance(explicit_people_names, list):
        _filter_owner_contacts_to_people(winner_id, explicit_people_names)
    else:
        # Fail closed: co-owner split must not be swallowed (silent loss of people).
        _merge_flat_owner_people(winner, loser)
    people_before = 0
    active_owner_ids_before: set[int] = set()
    try:
        from app.models.property_contact import PropertyContact
        active_owner_ids_before = {
            link.contact_id
            for link in PropertyContact.query.filter_by(
                property_id=winner_id,
                role='owner',
            ).all()
        }
        people_before = (
            PropertyContact.query.filter_by(property_id=winner_id, role='owner').count()
        )
    except Exception:  # noqa: BLE001
        people_before = 0
    contacts_combined = 0
    try:
        from app.services.contact_service import ContactService
        # Materialize flat owner_1 / owner_2 (incl. split joint names) as contacts
        # before same-person combine — otherwise jammed "Edwin and Yoyko" is lost.
        ContactService().upsert_owners_from_lead(
            winner,
            phone_source='flat_backfill',
            preserve_unmatched_owner_ids=active_owner_ids_before,
            commit=False,
            refresh_scoring=False,
        )
        contacts_combined = ContactService().unlink_duplicate_person_owners(winner_id)
    except Exception as exc:
        logger.warning(
            'same-person contact combine after merge failed winner=%s loser=%s: %s',
            winner_id,
            loser_id,
            exc,
        )
    if explicit_choices:
        _filter_owner_contact_methods(
            winner_id,
            phones=choices.get('phones') if isinstance(choices.get('phones'), list) else None,
            emails=choices.get('emails') if isinstance(choices.get('emails'), list) else None,
        )
    people_after = people_before
    try:
        from app.models.property_contact import PropertyContact
        people_after = (
            PropertyContact.query.filter_by(property_id=winner_id, role='owner').count()
        )
    except Exception:  # noqa: BLE001
        pass
    try:
        from app.services.lead_timeline_service import LeadTimelineService
        if explicit_choices:
            summary = f'Combined record #{loser_id} into this one with selected merge choices.'
        else:
            summary = (
                f'Combined record #{loser_id} into this one. '
                'People from both were kept; the same person got all phone numbers.'
            )
        LeadTimelineService().append(
            winner_id,
            'leads_merged',
            changed_by,
            summary,
            metadata={
                'loser_id': loser_id,
                'winner_id': winner_id,
                'people_kept': people_after,
                'contacts_combined': int(contacts_combined or 0),
                'selected_merge_choices': explicit_choices,
            },
            source='system',
            commit=False,
        )
    except Exception as exc:
        logger.warning(
            'timeline after merge failed winner=%s loser=%s: %s',
            winner_id,
            loser_id,
            exc,
        )
    try:
        from app.services.property_address_service import (
            ensure_lead_property_address_complete,
        )
        ensure_lead_property_address_complete(
            winner,
            actor='lead_dedup_merge',
            commit=False,
        )
    except Exception as exc:
        logger.warning(
            'property address completion after merge failed winner_id=%s: %s',
            winner_id,
            exc,
        )

    db.session.add(LeadAuditTrail(
        lead_id=winner_id,
        field_name='dedup_merge',
        old_value=str(loser_id),
        new_value=f"merged from lead {loser_id} ({loser.property_street})",
        changed_by=changed_by,
    ))
    db.session.delete(loser)
    logger.info("Merged lead %s into %s", loser_id, winner_id)


def find_duplicate_clusters() -> list[list[Lead]]:
    """Return groups of duplicate leads (same owner + dedup street key)."""
    from app.services.lead_merge_utils import cluster_same_building_by_owner_name

    # Require a last name column, or a multi-token first_name (jammed FULL NAME).
    rows = Lead.query.filter(
        Lead.owner_first_name.isnot(None),
        Lead.owner_first_name != '',
        Lead.property_street.isnot(None),
        Lead.property_street != '',
        or_(
            and_(Lead.owner_last_name.isnot(None), Lead.owner_last_name != ''),
            Lead.owner_first_name.contains(' '),
        ),
    ).all()

    return cluster_same_building_by_owner_name(
        rows,
        owner_user_id_of=lambda lead: lead.owner_user_id,
        street_of=lambda lead: lead.property_street,
        first_of=lambda lead: lead.owner_first_name,
        last_of=lambda lead: lead.owner_last_name,
    )


def find_building_owner_siblings(lead: Lead, *, limit: int = 40) -> list[Lead]:
    """Same property-owner leads whose street matches *lead* at building level.

    Matches on owner first/last name — not ``owner_user_id`` (CRM assignee).
    Assignees commonly own thousands of leads; filtering by assignee + a small
    id-ordered window misses same-building twins (e.g. street-only husk vs unit).
    """
    street = (lead.property_street or '').strip()
    lead_id = getattr(lead, 'id', None)
    if not street or not isinstance(lead_id, int):
        return []

    first = (lead.owner_first_name or '').strip()
    last = (lead.owner_last_name or '').strip()
    if not first:
        return []

    q = Lead.query.filter(
        Lead.id != lead_id,
        Lead.property_street.isnot(None),
        Lead.property_street != '',
    )
    q = _owner_name_filters(q, first, last)

    siblings: list[Lead] = []
    q = _street_prefilter(q, street)

    for other in q.order_by(Lead.id.asc()).limit(max(limit * 4, limit)).all():
        if streets_match_normalized(street, other.property_street):
            siblings.append(other)
        if len(siblings) >= limit:
            break
    return siblings


def find_same_building_leads(
    lead: Lead,
    *,
    limit: int = 8,
    owner_user_id: str | None = None,
) -> list[Lead]:
    """Same building-level street, regardless of owner name.

    Used by the lead-page merge banner so Yoko vs Yoko+Edwin still surface.
    Do not use the house-number ``1%`` prefilter — that scan is capped and
    drops real twins when many streets start with the same number.
    """
    street = (lead.property_street or '').strip()
    lead_id = getattr(lead, 'id', None)
    if not street or not isinstance(lead_id, int):
        return []

    base_query = Lead.query.filter(Lead.id != lead_id)
    if owner_user_id is not None:
        base_query = base_query.filter(Lead.owner_user_id == owner_user_id)

    key = dedup_street_key(street)
    if key:
        found: dict[int, Lead] = {}
        street_predicates = [
            Lead.normalized_street == key,
            Lead.normalized_street.ilike(f'{key} %'),
        ]
        # Pre-fix rows may still store glued dual house numbers ("18671869…").
        legacy_glued = legacy_glued_house_range_key(street)
        if legacy_glued and legacy_glued != key:
            street_predicates.append(Lead.normalized_street == legacy_glued)
            street_predicates.append(Lead.normalized_street.ilike(f'{legacy_glued} %'))
        house_token = key.split(' ', 1)[0]
        street_body = key.split(' ', 1)[1] if ' ' in key else ''
        if house_token.isdigit() and street_body:
            # Range twin stored as "1867-1869 …" / "1867/1869 …" with stale key.
            street_predicates.append(
                and_(
                    Lead.property_street.ilike(f'{house_token}-%'),
                    Lead.normalized_street.ilike(f'%{street_body}%'),
                ),
            )
            street_predicates.append(
                and_(
                    Lead.property_street.ilike(f'{house_token}/%'),
                    Lead.normalized_street.ilike(f'%{street_body}%'),
                ),
            )
            street_predicates.append(
                and_(
                    Lead.property_street.ilike(f'{house_token} &%'),
                    Lead.normalized_street.ilike(f'%{street_body}%'),
                ),
            )
        indexed_matches = (
            base_query.filter(or_(*street_predicates))
            .order_by(Lead.id.asc())
            .limit(max(limit * 8, 64))
            .all()
        )
        for other in indexed_matches:
            if streets_match_same_situs(street, other.property_street):
                found[other.id] = other
            if len(found) >= limit:
                break
        if len(found) < limit:
            missing_normalized = (
                base_query.filter(
                    or_(
                        Lead.normalized_street.is_(None),
                        Lead.normalized_street == '',
                    ),
                    func.lower(func.trim(Lead.property_street)) == street.lower(),
                )
                .order_by(Lead.id.asc())
                .limit(limit - len(found))
                .all()
            )
            for other in missing_normalized:
                if streets_match_same_situs(street, other.property_street):
                    found[other.id] = other
        return list(found.values())[:limit]

    siblings: list[Lead] = []
    q = base_query.filter(
        func.lower(func.trim(Lead.property_street)) == street.lower(),
    )
    for other in q.order_by(Lead.id.asc()).limit(limit).all():
        if streets_match_same_situs(street, other.property_street):
            siblings.append(other)
        if len(siblings) >= limit:
            break
    return siblings


def _lead_owner_display_name(lead: Lead) -> str:
    primary = ' '.join(
        p for p in (
            (lead.owner_first_name or '').strip(),
            (lead.owner_last_name or '').strip(),
        ) if p
    )
    second = ' '.join(
        p for p in (
            (getattr(lead, 'owner_2_first_name', None) or '').strip(),
            (getattr(lead, 'owner_2_last_name', None) or '').strip(),
        ) if p
    )
    if primary and second:
        return f'{primary} + {second}'
    return primary or second or f'Lead #{lead.id}'


def _people_names_for_lead_ids(lead_ids: list[int]) -> dict[int, list[str]]:
    """Active person names on each lead (owners, not companies / former)."""
    from app.models.contact import Contact
    from app.models.property_contact import PropertyContact
    from app.services.contact_service import _contact_display_name
    from app.services.plugins.owner_name_utils import (
        is_address_like_contact,
        is_entity_contact,
    )

    out: dict[int, list[str]] = {lid: [] for lid in lead_ids}
    if not lead_ids:
        return out
    rows = (
        db.session.query(Contact, PropertyContact)
        .join(PropertyContact, PropertyContact.contact_id == Contact.id)
        .filter(
            PropertyContact.property_id.in_(lead_ids),
            or_(
                PropertyContact.role.is_(None),
                PropertyContact.role != 'former_owner',
            ),
        )
        .order_by(PropertyContact.is_primary.desc(), PropertyContact.id.asc())
        .all()
    )
    seen: dict[int, set[str]] = {lid: set() for lid in lead_ids}
    for contact, link in rows:
        lid = link.property_id
        if lid not in out:
            continue
        if is_entity_contact(contact.first_name, contact.last_name):
            continue
        if is_address_like_contact(contact.first_name, contact.last_name):
            continue
        name = _contact_display_name(contact.first_name, contact.last_name)
        if name in seen[lid]:
            continue
        seen[lid].add(name)
        out[lid].append(name)
    return out


def same_address_lead_summaries(
    lead: Lead,
    *,
    limit: int = 8,
    owner_user_id: str | None = None,
    include_all_owners: bool = False,
) -> list[dict[str, Any]]:
    """Skinny same-building twins for the command-center merge banner."""
    scoped_owner_user_id = owner_user_id
    if not include_all_owners:
        scoped_owner_user_id = scoped_owner_user_id or getattr(lead, 'owner_user_id', None)
        if not scoped_owner_user_id:
            return []
    siblings = find_same_building_leads(
        lead,
        limit=limit,
        owner_user_id=scoped_owner_user_id,
    )
    if not siblings:
        return []
    names_by_id = _people_names_for_lead_ids([item.id for item in siblings])
    summaries: list[dict[str, Any]] = []
    for item in siblings:
        people = names_by_id.get(item.id) or []
        summaries.append({
            'id': item.id,
            'property_street': item.property_street,
            'owner_display_name': _lead_owner_display_name(item),
            'people_names': people,
        })
    return summaries


_CALL_EVENTS = frozenset({'call_logged', 'hubspot_call'})
_NOTE_EVENTS = frozenset({'note_added', 'hubspot_note'})
_EMAIL_EVENTS = frozenset({'email_logged'})
_MAIL_EVENTS = frozenset({'mail_queued', 'mail_sent', 'mail_delivered'})
_MERGE_CONTEXT_RELATED_CAP = 6


def _iso_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def _event_type_name(value: Any) -> str:
    raw = getattr(value, 'value', None)
    if isinstance(raw, str) and raw:
        return raw
    text = str(value or '')
    if '.' in text:
        return text.rsplit('.', 1)[-1]
    return text


def _empty_activity_summary() -> dict[str, Any]:
    return {
        'total': 0,
        'calls': 0,
        'notes': 0,
        'emails': 0,
        'mail': 0,
        'last_occurred_at': None,
        'last_summary': None,
        'last_event_type': None,
    }


def _activity_summaries_for_lead_ids(lead_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Timeline counts plus the latest non-deleted activity per lead."""
    from app.models.lead_timeline_entry import LeadTimelineEntry

    out = {lid: _empty_activity_summary() for lid in lead_ids}
    if not lead_ids:
        return out
    counts = (
        db.session.query(
            LeadTimelineEntry.lead_id,
            LeadTimelineEntry.event_type,
            func.count(LeadTimelineEntry.id),
        )
        .filter(
            LeadTimelineEntry.lead_id.in_(lead_ids),
            LeadTimelineEntry.is_deleted.is_(False),
        )
        .group_by(LeadTimelineEntry.lead_id, LeadTimelineEntry.event_type)
        .all()
    )
    for lead_id, event_type, count in counts:
        row = out.get(lead_id)
        if row is None:
            continue
        n = int(count or 0)
        row['total'] += n
        name = _event_type_name(event_type)
        if name in _CALL_EVENTS:
            row['calls'] += n
        elif name in _NOTE_EVENTS:
            row['notes'] += n
        elif name in _EMAIL_EVENTS:
            row['emails'] += n
        elif name in _MAIL_EVENTS:
            row['mail'] += n

    latest_at = (
        db.session.query(
            LeadTimelineEntry.lead_id.label('lead_id'),
            func.max(LeadTimelineEntry.occurred_at).label('occurred_at'),
        )
        .filter(
            LeadTimelineEntry.lead_id.in_(lead_ids),
            LeadTimelineEntry.is_deleted.is_(False),
        )
        .group_by(LeadTimelineEntry.lead_id)
        .subquery()
    )
    latest_rows = (
        db.session.query(LeadTimelineEntry)
        .join(
            latest_at,
            and_(
                LeadTimelineEntry.lead_id == latest_at.c.lead_id,
                LeadTimelineEntry.occurred_at == latest_at.c.occurred_at,
            ),
        )
        .filter(LeadTimelineEntry.is_deleted.is_(False))
        .all()
    )
    best: dict[int, LeadTimelineEntry] = {}
    for entry in latest_rows:
        current = best.get(entry.lead_id)
        if current is None or entry.id > current.id:
            best[entry.lead_id] = entry
    for lead_id, entry in best.items():
        row = out.get(lead_id)
        if row is None:
            continue
        summary = (entry.summary or '').strip()
        row['last_occurred_at'] = _iso_or_none(entry.occurred_at)
        row['last_summary'] = summary[:180] if summary else None
        row['last_event_type'] = _event_type_name(entry.event_type) or None
    return out


def _open_task_counts_for_lead_ids(lead_ids: list[int]) -> dict[int, int]:
    from app.models.lead_task import LeadTask

    if not lead_ids:
        return {}
    rows = (
        db.session.query(LeadTask.lead_id, func.count(LeadTask.id))
        .filter(
            LeadTask.lead_id.in_(lead_ids),
            LeadTask.status == 'open',
        )
        .group_by(LeadTask.lead_id)
        .all()
    )
    return {int(lead_id): int(count or 0) for lead_id, count in rows}


def _organization_names_for_lead_ids(lead_ids: list[int]) -> dict[int, list[str]]:
    from app.models.organization import Organization
    from app.models.property_organization_link import PropertyOrganizationLink

    out: dict[int, list[str]] = {lid: [] for lid in lead_ids}
    if not lead_ids:
        return out
    rows = (
        db.session.query(PropertyOrganizationLink.property_id, Organization.name)
        .join(Organization, Organization.id == PropertyOrganizationLink.organization_id)
        .filter(PropertyOrganizationLink.property_id.in_(lead_ids))
        .order_by(PropertyOrganizationLink.id.asc())
        .all()
    )
    seen: dict[int, set[str]] = {lid: set() for lid in lead_ids}
    for property_id, name in rows:
        label = (name or '').strip()
        if not label or property_id not in out or label in seen[property_id]:
            continue
        if len(out[property_id]) >= 4:
            continue
        seen[property_id].add(label)
        out[property_id].append(label)
    return out


def _confirmed_hubspot_ids_among(lead_ids: list[int]) -> set[int]:
    if not lead_ids:
        return set()
    rows = HubSpotMatch.query.filter(
        HubSpotMatch.internal_record_type == 'lead',
        HubSpotMatch.status == 'confirmed',
        HubSpotMatch.internal_record_id.in_(lead_ids),
    ).all()
    return {int(row.internal_record_id) for row in rows if row.internal_record_id is not None}


def _related_properties_for_merge(leads: list[Lead]) -> dict[int, list[dict[str, Any]]]:
    """Other buildings for the same person — capped, never blocks the dialog."""
    from app.services.contact_service import ContactService

    svc = ContactService()
    out: dict[int, list[dict[str, Any]]] = {}
    for lead in leads:
        try:
            rows = svc.get_related_properties(lead.id, limit=_MERGE_CONTEXT_RELATED_CAP)
        except Exception:  # noqa: BLE001 — decision context is best-effort
            logger.exception('related properties for merge context failed lead=%s', lead.id)
            rows = []
        skinny: list[dict[str, Any]] = []
        for row in rows:
            prop_id = row.get('id')
            if not prop_id:
                continue
            skinny.append({
                'id': prop_id,
                'property_street': row.get('property_street'),
                'property_city': row.get('property_city'),
                'lead_status': row.get('lead_status'),
                'lead_score': row.get('lead_score'),
            })
        out[lead.id] = skinny
    return out


def _contact_methods_for_merge(leads: list[Lead]) -> dict[int, dict[str, list[str]]]:
    """Actual phone numbers and emails on each lead, not just yes/no flags."""
    from app.services.outreach_method_service import _collect_emails_for_lead
    from app.services.phone_confidence_service import PhoneConfidenceService

    out: dict[int, dict[str, list[str]]] = {}
    for lead in leads:
        phones: list[str] = []
        try:
            seen: set[str] = set()
            for item in PhoneConfidenceService.build_phones_payload(lead.id, lead):
                value = str(item.get('value') or '').strip()
                if not value:
                    continue
                key = PhoneConfidenceService.normalize_phone(value) or value.lower()
                if key in seen:
                    continue
                seen.add(key)
                phones.append(value)
        except Exception:  # noqa: BLE001 — decision context is best-effort
            logger.exception('phones for merge context failed lead=%s', lead.id)
            phones = []
        try:
            emails = _collect_emails_for_lead(lead.id, lead)
        except Exception:  # noqa: BLE001
            logger.exception('emails for merge context failed lead=%s', lead.id)
            emails = []
        out[lead.id] = {'phones': phones, 'emails': emails}
    return out


def _merge_decision_row(
    lead: Lead,
    *,
    people: list[str],
    activity: dict[str, Any],
    open_task_count: int,
    organizations: list[str],
    hubspot_confirmed: bool,
    related_properties: list[dict[str, Any]],
    phones: list[str],
    emails: list[str],
) -> dict[str, Any]:
    score = getattr(lead, 'lead_score', None)
    return {
        'id': lead.id,
        'property_street': lead.property_street,
        'property_city': lead.property_city,
        'property_state': lead.property_state,
        'property_zip': lead.property_zip,
        'owner_display_name': _lead_owner_display_name(lead),
        'people_names': people,
        'county_assessor_pin': getattr(lead, 'county_assessor_pin', None),
        'property_type': lead.property_type,
        'units': lead.units,
        'lead_status': lead.lead_status,
        'lead_score': float(score) if score is not None else None,
        'source': (lead.source or '').strip() or None,
        'deal_source': (lead.deal_source or '').strip() or None,
        'data_source': (lead.data_source or '').strip() or None,
        'source_type': (getattr(lead, 'source_type', None) or '').strip() or None,
        'created_at': _iso_or_none(lead.created_at),
        'last_contact_date': _iso_or_none(lead.last_contact_date),
        'date_added_to_hubspot': _iso_or_none(lead.date_added_to_hubspot),
        'hubspot_confirmed': hubspot_confirmed,
        'has_phone': bool(phones) or bool(lead.has_phone),
        'has_email': bool(emails) or bool(lead.has_email),
        'phones': phones,
        'emails': emails,
        'open_task_count': int(open_task_count or 0),
        'organizations': organizations,
        'activity': activity,
        'related_properties': related_properties,
    }


def merge_decision_summaries(leads: list[Lead]) -> list[dict[str, Any]]:
    """Property, source, portfolio, and activity context for the merge dialog."""
    if not leads:
        return []
    ids = [lead.id for lead in leads]
    names = _people_names_for_lead_ids(ids)
    activity = _activity_summaries_for_lead_ids(ids)
    tasks = _open_task_counts_for_lead_ids(ids)
    organizations = _organization_names_for_lead_ids(ids)
    confirmed = _confirmed_hubspot_ids_among(ids)
    related = _related_properties_for_merge(leads)
    methods = _contact_methods_for_merge(leads)
    return [
        _merge_decision_row(
            lead,
            people=names.get(lead.id) or [],
            activity=activity.get(lead.id) or _empty_activity_summary(),
            open_task_count=tasks.get(lead.id, 0),
            organizations=organizations.get(lead.id) or [],
            hubspot_confirmed=lead.id in confirmed,
            related_properties=related.get(lead.id) or [],
            phones=(methods.get(lead.id) or {}).get('phones') or [],
            emails=(methods.get(lead.id) or {}).get('emails') or [],
        )
        for lead in leads
    ]


def merge_preview_for_ids(lead_id: int, other_id: int) -> dict[str, Any]:
    """Validate same-building merge and return decision context for both sides."""
    if lead_id == other_id:
        raise ValueError('winner and loser must be different leads')
    lead = db.session.get(Lead, lead_id)
    other = db.session.get(Lead, other_id)
    if lead is None or other is None:
        raise ValueError('winner or loser lead not found')
    same_building = streets_match_same_situs(lead.property_street, other.property_street)
    mergeable = streets_match_duplicate_merge(lead.property_street, other.property_street)
    by_id = {row['id']: row for row in merge_decision_summaries([lead, other])}
    return {
        'same_building': bool(same_building),
        'mergeable': bool(mergeable),
        'current': by_id[lead.id],
        'other': by_id[other.id],
    }


def cluster_preview_for_lead(lead: Lead) -> dict[str, Any] | None:
    """Suggested soft-merge cluster for Needs Review (duplicate_lead_cluster)."""
    siblings = find_building_owner_siblings(lead)
    if not siblings:
        return None
    cluster = [lead] + siblings
    confirmed_ids = confirmed_hubspot_lead_ids()
    records = [_lead_to_merge_record(item) for item in cluster]
    winner = pick_merge_winner(records, confirmed_ids)
    lead_owner_user_id = getattr(lead, 'owner_user_id', None)
    visible_name_ids = [
        item.id for item in cluster
        if item.id == lead.id or (
            lead_owner_user_id and getattr(item, 'owner_user_id', None) == lead_owner_user_id
        )
    ]
    names = _people_names_for_lead_ids(visible_name_ids)
    members = []
    for item in cluster:
        members.append({
            'id': item.id,
            'property_street': item.property_street,
            'owner_display_name': _lead_owner_display_name(item),
            'county_assessor_pin': getattr(item, 'county_assessor_pin', None),
            'lead_status': item.lead_status,
            'has_phone': bool(item.has_phone),
            'has_email': bool(item.has_email),
            'hubspot_confirmed': item.id in confirmed_ids,
            'is_suggested_winner': item.id == winner['id'],
            'people_names': names.get(item.id) or [],
        })
    return {
        'cluster_ids': [item.id for item in cluster],
        'suggested_winner_id': winner['id'],
        'confidence': merge_confidence(records, confirmed_ids),
        'streets': {
            item.id: item.property_street for item in cluster
        },
        'members': members,
    }


def merge_loser_into_winner(
    winner_id: int,
    loser_id: int,
    *,
    changed_by: str = 'manual_soft_merge',
    commit: bool = True,
    choices: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge *loser_id* into *winner_id*; clear duplicate review flags on winner."""
    if winner_id == loser_id:
        raise ValueError('winner and loser must be different leads')
    winner = db.session.get(Lead, winner_id)
    loser = db.session.get(Lead, loser_id)
    if winner is None or loser is None:
        raise ValueError('winner or loser lead not found')
    if not streets_match_duplicate_merge(winner.property_street, loser.property_street):
        raise ValueError('leads do not share the same address / unit')

    try:
        with db.session.begin_nested():
            merge_lead_into_winner(winner, loser, changed_by=changed_by, choices=choices)
            winner.review_required = False
            if winner.review_reason == 'duplicate_lead_cluster':
                winner.review_reason = None
                winner.review_triggered_at = None

        if commit:
            db.session.commit()
            from app.services.lead_refresh import refresh_lead_scoring
            refresh_lead_scoring(winner_id)
    except IntegrityError:
        db.session.rollback()
        logger.exception(
            'merge blocked by a unique constraint winner=%s loser=%s',
            winner_id,
            loser_id,
        )
        raise ValueError(
            'Combine could not finish because another record already uses that owner, address, or PIN.'
        ) from None

    return {
        'winner_id': winner_id,
        'loser_id': loser_id,
        'merged': True,
    }


def try_absorb_duplicate_for_lead(
    lead: Lead,
    *,
    changed_by: str = 'situs_sibling_absorb',
) -> dict[str, Any] | None:
    """Auto-merge clear same-building duplicates; flag ambiguous for Needs Review.

    Returns a result dict, or None when no siblings exist.
    """
    siblings = find_building_owner_siblings(lead)
    if not siblings:
        return None

    cluster = [lead] + siblings
    confirmed_ids = confirmed_hubspot_lead_ids()
    records = [_lead_to_merge_record(item) for item in cluster]
    confidence = merge_confidence(records, confirmed_ids)

    if confidence == 'ambiguous':
        for item in cluster:
            item.review_required = True
            item.review_reason = 'duplicate_lead_cluster'
            item.review_triggered_at = datetime.utcnow()
        return {
            'flagged': True,
            'cluster_ids': [item.id for item in cluster],
            'confidence': confidence,
        }

    winner_record = pick_merge_winner(records, confirmed_ids)
    winner = next(item for item in cluster if item.id == winner_record['id'])
    losers = [item for item in cluster if item.id != winner.id]
    merged_pairs: list[dict[str, int]] = []

    for loser in losers:
        try:
            with db.session.begin_nested():
                # Re-load winner after prior merges.
                winner = db.session.get(Lead, winner_record['id'])
                loser = db.session.get(Lead, loser.id)
                if winner is None or loser is None:
                    break
                pair = {
                    'winner_id': winner.id,
                    'loser_id': loser.id,
                }
                merge_lead_into_winner(winner, loser, changed_by=changed_by)
            merged_pairs.append(pair)
        except Exception:
            logger.exception(
                'absorb merge failed loser=%s winner=%s',
                getattr(loser, 'id', None),
                winner_record['id'],
            )
            continue

    if winner is not None:
        winner.review_required = False
        if winner.review_reason == 'duplicate_lead_cluster':
            winner.review_reason = None
            winner.review_triggered_at = None

    return {
        'merged': bool(merged_pairs),
        'merged_pairs': merged_pairs,
        'winner_id': winner_record['id'],
        'confidence': confidence,
    }


def run_duplicate_sentinel(
    *,
    dry_run: bool = False,
    max_merges: int = 100,
) -> dict:
    """Scan for duplicate clusters; auto-merge clear winners, flag ambiguous.

    Returns counts plus ``merged_pairs`` ``[{winner_id, loser_id}, ...]`` for
    dry-run previews and post-apply verification.
    """
    confirmed_ids = confirmed_hubspot_lead_ids()
    clusters = find_duplicate_clusters()
    stats: dict = {
        'clusters_found': len(clusters),
        'merged': 0,
        'flagged': 0,
        'skipped': 0,
        'merged_pairs': [],
    }
    winners_to_rescore: set[int] = set()

    for cluster in clusters:
        if stats['merged'] >= max_merges:
            stats['skipped'] += 1
            continue

        records = [_lead_to_merge_record(lead) for lead in cluster]
        confidence = merge_confidence(records, confirmed_ids)

        if confidence == 'ambiguous':
            if not dry_run:
                for lead in cluster:
                    lead.review_required = True
                    lead.review_reason = 'duplicate_lead_cluster'
                    lead.review_triggered_at = datetime.utcnow()
            stats['flagged'] += len(cluster)
            continue

        winner_record = pick_merge_winner(records, confirmed_ids)
        winner = next(l for l in cluster if l.id == winner_record['id'])
        losers = [l for l in cluster if l.id != winner.id]

        for loser in losers:
            # Enforce max-merges per loser, not only per cluster.
            if stats['merged'] >= max_merges:
                stats['skipped'] += 1
                break
            pair = {
                'winner_id': winner.id,
                'loser_id': loser.id,
                'winner_street': winner.property_street,
                'loser_street': loser.property_street,
            }
            if dry_run:
                stats['merged_pairs'].append(pair)
                stats['merged'] += 1
                continue
            try:
                # Isolate each pair so a later failure cannot undo earlier merges.
                with db.session.begin_nested():
                    merge_lead_into_winner(winner, loser)
                stats['merged_pairs'].append(pair)
                stats['merged'] += 1
                winners_to_rescore.add(winner.id)
            except Exception:
                logger.exception(
                    "Failed merging lead %s into %s — skipping pair",
                    loser.id, winner.id,
                )
                stats['skipped'] += 1
                winner = db.session.get(Lead, winner_record['id'])
                if winner is None:
                    break
                continue

    if not dry_run:
        # Commit merges before rescoring — refresh_lead_scoring rolls back the
        # shared session on failure and must not undo an in-flight merge.
        db.session.commit()
        from app.services.lead_refresh import refresh_lead_scoring
        for winner_id in winners_to_rescore:
            refresh_lead_scoring(winner_id)
    else:
        db.session.rollback()

    logger.info("Duplicate sentinel complete: %s", {
        k: v for k, v in stats.items() if k != 'merged_pairs'
    })
    return stats
