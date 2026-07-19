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


def _prefer_cleaner_property_street(winner: Lead, loser: Lead) -> None:
    """Prefer a street line without a glued ZIP when both normalize to one building."""
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
    if w_has_zip and not l_has_zip:
        winner.property_street = l_street
        refresh_lead_dedup_fields(winner)


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
        if (w_val is None or w_val == '') and l_val not in (None, ''):
            setattr(winner, field, l_val)

    _prefer_newer_sale_onto_winner(winner, loser)
    _prefer_cleaner_property_street(winner, loser)

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
            stats['merged_pairs'].append({
                'winner_id': winner.id,
                'loser_id': loser.id,
                'winner_street': winner.property_street,
                'loser_street': loser.property_street,
            })
            if dry_run:
                stats['merged'] += 1
                continue
            try:
                merge_lead_into_winner(winner, loser)
                stats['merged'] += 1
                winners_to_rescore.add(winner.id)
            except Exception:
                db.session.rollback()
                logger.exception(
                    "Failed merging lead %s into %s — skipping pair",
                    loser.id, winner.id,
                )
                stats['skipped'] += 1
                # Reload winner after rollback so later losers in the cluster
                # still see a live ORM instance.
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
