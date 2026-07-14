"""Backfill HubSpot Interactions into Command Center LeadTimelineEntry rows.

Bridges existing hubspot_import Interactions (note/call/email/meeting) that are
associated to a lead into LeadTimelineEntry via HubSpotTimelineImportService.
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

_backend_dir = Path(__file__).resolve().parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

from env_loader import load_project_env

load_project_env()

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger('backfill_hubspot_interactions_to_timeline')

from app import create_app, db
from app.models import Interaction, InteractionAssociation, LeadTimelineEntry
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
        lead_ids = _lead_ids_with_bridgeable_interactions(args.lead_id)
        logger.info('Found %s lead(s) with HubSpot interactions to bridge', len(lead_ids))
        print(f'Found {len(lead_ids)} lead(s) with HubSpot interactions', flush=True)

        would_create = 0
        for lid in lead_ids:
            missing = _missing_count_for_lead(lid)
            if missing:
                would_create += missing
                print(f'lead_id={lid} missing_timeline_entries={missing}', flush=True)

        if not args.apply:
            print(
                f'Done (dry-run): leads={len(lead_ids)} '
                f'would_create~={would_create}',
                flush=True,
            )
            return

        svc = HubSpotTimelineImportService()
        results = svc.sync_leads_from_interactions(lead_ids, mark_review=False)
        failed_ids = [lid for lid, count in results.items() if count < 0]
        created = sum(count for count in results.values() if count > 0)
        logger.info(
            'Done (applied): leads=%s new_entries=%s failed=%s',
            len(results),
            created,
            len(failed_ids),
        )
        print(
            f'Done (applied): leads={len(results)} new_entries={created} '
            f'failed={len(failed_ids)}',
            flush=True,
        )
        if failed_ids:
            print(f'Failed lead ids: {failed_ids[:50]}', flush=True)
            sys.exit(1)


if __name__ == '__main__':
    main()
