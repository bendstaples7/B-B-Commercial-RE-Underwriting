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
    merge_mailer_history,
    pick_merge_winner,
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
        if _dedup_index_conflict_exists(
            lead=winner,
            proposed_street=preferred,
            ignore_ids={winner.id} if isinstance(winner.id, int) else set(),
        ):
            logger.info(
                'skipping cleaner street preference for winner=%s; normalized street would collide',
                winner.id,
            )
            return
        winner.property_street = preferred
        refresh_lead_dedup_fields(winner)
        # Address completion runs once at merge level — avoid double GIS here.


def merge_lead_into_winner(winner: Lead, loser: Lead, *, changed_by: str = 'dedup_sentinel') -> None:
    """Merge loser into winner (ORM). Caller must commit."""
    winner_id = winner.id
    loser_id = loser.id

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
    # Fail closed: co-owner split must not be swallowed (silent loss of people).
    _merge_flat_owner_people(winner, loser)
    people_before = 0
    try:
        from app.models.property_contact import PropertyContact
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
        LeadTimelineService().append(
            winner_id,
            'leads_merged',
            changed_by,
            (
                f'Combined record #{loser_id} into this one. '
                'People from both were kept; the same person got all phone numbers.'
            ),
            metadata={
                'loser_id': loser_id,
                'winner_id': winner_id,
                'people_kept': people_after,
                'contacts_combined': int(contacts_combined or 0),
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
        indexed_matches = (
            base_query.filter(
                or_(
                    Lead.normalized_street == key,
                    Lead.normalized_street.ilike(f'{key} %'),
                ),
            )
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


def merge_preview_for_ids(lead_id: int, other_id: int) -> dict[str, Any]:
    """Validate same-building merge and return people on both sides."""
    if lead_id == other_id:
        raise ValueError('winner and loser must be different leads')
    lead = db.session.get(Lead, lead_id)
    other = db.session.get(Lead, other_id)
    if lead is None or other is None:
        raise ValueError('winner or loser lead not found')
    same_building = streets_match_same_situs(lead.property_street, other.property_street)
    names = _people_names_for_lead_ids([lead_id, other_id])
    return {
        'same_building': bool(same_building),
        'current': {
            'id': lead.id,
            'property_street': lead.property_street,
            'owner_display_name': _lead_owner_display_name(lead),
            'people_names': names.get(lead_id) or [],
        },
        'other': {
            'id': other.id,
            'property_street': other.property_street,
            'owner_display_name': _lead_owner_display_name(other),
            'people_names': names.get(other_id) or [],
        },
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
    return {
        'cluster_ids': [item.id for item in cluster],
        'suggested_winner_id': winner['id'],
        'confidence': merge_confidence(records, confirmed_ids),
        'streets': {
            item.id: item.property_street for item in cluster
        },
    }


def merge_loser_into_winner(
    winner_id: int,
    loser_id: int,
    *,
    changed_by: str = 'manual_soft_merge',
    commit: bool = True,
) -> dict[str, Any]:
    """Merge *loser_id* into *winner_id*; clear duplicate review flags on winner."""
    if winner_id == loser_id:
        raise ValueError('winner and loser must be different leads')
    winner = db.session.get(Lead, winner_id)
    loser = db.session.get(Lead, loser_id)
    if winner is None or loser is None:
        raise ValueError('winner or loser lead not found')
    if not streets_match_same_situs(winner.property_street, loser.property_street):
        raise ValueError('leads do not share the same address / unit')

    with db.session.begin_nested():
        merge_lead_into_winner(winner, loser, changed_by=changed_by)
        winner.review_required = False
        if winner.review_reason == 'duplicate_lead_cluster':
            winner.review_reason = None
            winner.review_triggered_at = None

    if commit:
        db.session.commit()
        from app.services.lead_refresh import refresh_lead_scoring
        refresh_lead_scoring(winner_id)

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
