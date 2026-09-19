"""Backfill HubSpot Interactions into Command Center LeadTimelineEntry rows.

Bridges existing hubspot_import Interactions (note/call/email/meeting) that are
associated to a lead into LeadTimelineEntry via HubSpotTimelineImportService.
Also converts stored HubSpot MEETING engagements that predate meeting support.
Uses mark_review=False so historical backfill does not flood Needs Review.

Dry-run by default. Pass --apply to mutate the database.

Run from backend/:
    python scripts/backfill_hubspot_interactions_to_timeline.py [--apply] [--lead-id N]
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from sqlalchemy import func

_backend_dir = Path(__file__).resolve().parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

from env_loader import load_project_env

load_project_env()

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger('backfill_hubspot_interactions_to_timeline')

from app import create_app, db
from app.models import (
    HubSpotEngagement,
    HubSpotMatch,
    Interaction,
    InteractionAssociation,
    LeadTimelineEntry,
)
from app.services.hubspot_activity_converter_service import (
    HubSpotActivityConverterService,
)
from app.services.hubspot_timeline_import_service import (
    BRIDGE_INTERACTION_TYPES,
    HubSpotTimelineImportService,
)


def _lead_ids_with_bridgeable_interactions(lead_id: int | None) -> list[int]:
    q = (
        db.session.query(InteractionAssociation.target_id)
        .join(Interaction, Interaction.id == InteractionAssociation.interaction_id)
        .filter(
            InteractionAssociation.target_type == 'lead',
            Interaction.source == 'hubspot_import',
            Interaction.hubspot_engagement_id.isnot(None),
            Interaction.interaction_type.in_(tuple(BRIDGE_INTERACTION_TYPES)),
        )
        .distinct()
        .order_by(InteractionAssociation.target_id.asc())
    )
    if lead_id is not None:
        q = q.filter(InteractionAssociation.target_id == lead_id)
    return [int(row[0]) for row in q.all()]


def _missing_count_for_lead(lead_id: int) -> int:
    """Count HubSpot engagement ids associated to lead that lack a timeline entry.

    Respects the global unique index on hubspot_activity_id — ids already stored
    on another lead are not counted as missing.
    """
    engagement_ids = {
        str(row[0])
        for row in (
            db.session.query(Interaction.hubspot_engagement_id)
            .join(
                InteractionAssociation,
                InteractionAssociation.interaction_id == Interaction.id,
            )
            .filter(
                InteractionAssociation.target_type == 'lead',
                InteractionAssociation.target_id == lead_id,
                Interaction.source == 'hubspot_import',
                Interaction.hubspot_engagement_id.isnot(None),
                Interaction.interaction_type.in_(tuple(BRIDGE_INTERACTION_TYPES)),
            )
            .all()
        )
        if row[0]
    }
    if not engagement_ids:
        return 0
    existing = {
        str(row[0])
        for row in (
            db.session.query(LeadTimelineEntry.hubspot_activity_id)
            .filter(LeadTimelineEntry.hubspot_activity_id.in_(engagement_ids))
            .all()
        )
        if row[0]
    }
    return len(engagement_ids - existing)


def _association_id_pairs(raw_payload: dict | None) -> set[tuple[str, str]]:
    """HubSpot (record_type, id) pairs from an engagement associations block."""
    assoc = (raw_payload or {}).get('associations') or {}
    pairs: set[tuple[str, str]] = set()
    for payload_key, record_type in (
        ('dealIds', 'deal'),
        ('contactIds', 'contact'),
        ('companyIds', 'company'),
    ):
        for hs_id in assoc.get(payload_key) or []:
            if hs_id is None or str(hs_id) == '':
                continue
            pairs.add((record_type, str(hs_id)))
    return pairs


def _confirmed_match_pairs_for_lead(lead_id: int) -> set[tuple[str, str]]:
    return {
        (row.hubspot_record_type, str(row.hubspot_id))
        for row in (
            db.session.query(HubSpotMatch.hubspot_record_type, HubSpotMatch.hubspot_id)
            .filter(
                HubSpotMatch.internal_record_type == 'lead',
                HubSpotMatch.internal_record_id == lead_id,
                HubSpotMatch.status == 'confirmed',
            )
            .all()
        )
    }


def _meeting_engagements_missing_interactions(
    lead_id: int | None = None,
) -> list[HubSpotEngagement]:
    """Return stored HubSpot MEETING engagements that still need Interactions."""
    existing_interaction_ids = (
        db.session.query(Interaction.hubspot_engagement_id)
        .filter(Interaction.hubspot_engagement_id.isnot(None))
        .subquery()
    )
    q = (
        HubSpotEngagement.query
        .outerjoin(
            existing_interaction_ids,
            HubSpotEngagement.hubspot_id
            == existing_interaction_ids.c.hubspot_engagement_id,
        )
        .filter(func.upper(HubSpotEngagement.engagement_type) == 'MEETING')
        .filter(existing_interaction_ids.c.hubspot_engagement_id.is_(None))
        .order_by(HubSpotEngagement.id.asc())
    )
    if lead_id is None:
        return q.all()

    wanted = _confirmed_match_pairs_for_lead(lead_id)
    if not wanted:
        return []

    from sqlalchemy import String, cast, or_

    id_filters = [
        cast(HubSpotEngagement.raw_payload, String).contains(hs_id)
        for _, hs_id in wanted
        if hs_id
    ]
    if id_filters:
        q = q.filter(or_(*id_filters))

    return [
        engagement
        for engagement in q.all()
        if _association_id_pairs(engagement.raw_payload) & wanted
    ]


def convert_missing_meeting_interactions(lead_id: int | None = None) -> tuple[int, int]:
    """Convert stored HubSpot MEETING engagements into Interactions.

    Returns ``(created, failed)``. The converter is idempotent; this helper only
    selects engagements without an Interaction so repeated script runs are cheap.
    """
    converter = HubSpotActivityConverterService()
    created = 0
    failed = 0

    for engagement in _meeting_engagements_missing_interactions(lead_id):
        if lead_id is not None:
            assoc_lead_ids = {
                int(assoc['target_id'])
                for assoc in converter.associations_for_engagement(engagement)
                if assoc.get('target_type') == 'lead'
                and assoc.get('target_id') is not None
            }
            if assoc_lead_ids - {lead_id}:
                failed += 1
                logger.warning(
                    'Skipping HubSpot MEETING engagement hubspot_id=%s for '
                    '--lead-id=%s because it also matches lead ids %s',
                    engagement.hubspot_id,
                    lead_id,
                    sorted(assoc_lead_ids - {lead_id}),
                )
                continue
        try:
            result = converter.convert_engagement(engagement)
        except Exception as exc:
            db.session.rollback()
            failed += 1
            logger.warning(
                'Failed to convert HubSpot MEETING engagement hubspot_id=%s: %s',
                engagement.hubspot_id,
                exc,
            )
            continue
        if result is not None:
            created += 1

    return created, failed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--apply',
        action='store_true',
        help='Write LeadTimelineEntry rows (default is dry-run)',
    )
    parser.add_argument(
        '--lead-id',
        type=int,
        default=None,
        help='Only sync this lead id',
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        meetings_to_convert = _meeting_engagements_missing_interactions(args.lead_id)
        lead_ids = _lead_ids_with_bridgeable_interactions(args.lead_id)
        logger.info('Found %s lead(s) with HubSpot interactions to bridge', len(lead_ids))
        print(f'Found {len(lead_ids)} lead(s) with HubSpot interactions', flush=True)
        if meetings_to_convert:
            print(
                f'Found {len(meetings_to_convert)} stored HubSpot meeting engagement(s) '
                'without Interactions',
                flush=True,
            )

        would_create = 0
        for lid in lead_ids:
            missing = _missing_count_for_lead(lid)
            if missing:
                would_create += missing
                print(f'lead_id={lid} missing_timeline_entries={missing}', flush=True)

        if not args.apply:
            print(
                f'Done (dry-run): leads={len(lead_ids)} '
                f'would_create~={would_create} '
                f'would_convert_meetings={len(meetings_to_convert)}',
                flush=True,
            )
            return

        converted, conversion_failures = convert_missing_meeting_interactions(
            args.lead_id,
        )
        if converted:
            print(f'Converted {converted} HubSpot meeting Interaction(s)', flush=True)
        if conversion_failures:
            print(f'Failed meeting conversions: {conversion_failures}', flush=True)

        lead_ids = _lead_ids_with_bridgeable_interactions(args.lead_id)
        svc = HubSpotTimelineImportService()
        results = svc.sync_leads_from_interactions(lead_ids, mark_review=False)
        failed_ids = [lid for lid, count in results.items() if count < 0]
        created = sum(count for count in results.values() if count > 0)
        logger.info(
            'Done (applied): leads=%s new_entries=%s failed=%s conversion_failures=%s',
            len(results),
            created,
            len(failed_ids),
            conversion_failures,
        )
        print(
            f'Done (applied): leads={len(results)} new_entries={created} '
            f'failed={len(failed_ids)}',
            flush=True,
        )
        if failed_ids:
            print(f'Failed lead ids: {failed_ids[:50]}', flush=True)
        if conversion_failures or failed_ids:
            sys.exit(1)


if __name__ == '__main__':
    main()
