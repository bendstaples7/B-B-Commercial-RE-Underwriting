"""Diagnostic: HubSpot task state and recommended-action timeline for a lead.

Read-only by default. Searches Gilberto/Hilberto Olivares by default; pass --first/--last.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()


def _parse_args():
    parser = argparse.ArgumentParser(description='Diagnose lead RA and HubSpot tasks.')
    parser.add_argument('--first', default='gilberto', help='Owner first name ILIKE pattern')
    parser.add_argument('--last', default='olivares', help='Owner last name ILIKE pattern')
    parser.add_argument(
        '--date',
        default='2026-06-25',
        help='Timeline window date (UTC), YYYY-MM-DD',
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    window_start = datetime.fromisoformat(args.date).replace(tzinfo=timezone.utc)
    window_end = window_start.replace(hour=23, minute=59, second=59)

    from sqlalchemy import or_, text

    from app import create_app, db
    from app.models.hubspot_engagement import HubSpotEngagement
    from app.models.lead import Property as Lead
    from app.models.lead_timeline_entry import LeadTimelineEntry
    from app.services.action_engine_service import (
        ActionEngineService,
        evaluate_recommended_action,
    )

    app = create_app()
    with app.app_context():
        leads = Lead.query.filter(
            Lead.owner_first_name.ilike(f'%{args.first}%'),
            Lead.owner_last_name.ilike(f'%{args.last}%'),
        ).all()
        print('leads_found', len(leads))
        if not leads:
            return 1

        for lead in leads[:5]:
            print('\n=== LEAD ===')
            print(
                'lead_id', lead.id,
                lead.owner_first_name, lead.owner_last_name,
                'ra=', lead.recommended_action,
                'score=', lead.lead_score,
                'is_warm=', lead.is_warm,
                'status=', lead.lead_status,
            )

            computed, winning_rule, signals = evaluate_recommended_action(lead)
            print('engine_computed', computed, 'winning_rule', winning_rule, 'signals', signals)
            print('api_signals', ActionEngineService.get_winning_rule_signals(lead))

            entries = (
                LeadTimelineEntry.query
                .filter_by(lead_id=lead.id)
                .filter(
                    LeadTimelineEntry.occurred_at >= window_start,
                    LeadTimelineEntry.occurred_at <= window_end,
                )
                .order_by(LeadTimelineEntry.occurred_at)
                .all()
            )
            print(f'\n=== TIMELINE {args.date} UTC ({len(entries)} events) ===')
            for entry in entries:
                marker = '>>>' if entry.event_type == 'recommended_action_changed' else '   '
                print(
                    marker,
                    entry.occurred_at,
                    entry.event_type,
                    entry.summary[:120],
                )
                if entry.event_type == 'recommended_action_changed' and entry.event_metadata:
                    print('       metadata', entry.event_metadata)

            native = db.session.execute(
                text(
                    "SELECT id, title, status FROM lead_tasks "
                    "WHERE lead_id = :lid AND status = 'open'"
                ),
                {'lid': lead.id},
            ).fetchall()
            hs = db.session.execute(
                text("""
                    SELECT t.id, t.title, t.status, t.hubspot_task_id, t.due_date
                    FROM tasks t
                    JOIN task_associations ta ON ta.task_id = t.id
                    WHERE ta.target_type = 'lead' AND ta.target_id = :lid
                      AND t.status IN ('open', 'overdue')
                      AND t.source = 'hubspot_import'
                """),
                {'lid': lead.id},
            ).fetchall()
            print('\n=== OPEN TASKS ===')
            print('  native_open', native)
            print('  hubspot_open', hs)
            for row in hs:
                hs_id = row[3]
                eng = HubSpotEngagement.query.filter_by(hubspot_id=str(hs_id)).first()
                hs_status = (
                    (eng.raw_payload.get('metadata') or {}).get('status')
                    if eng and eng.raw_payload else None
                )
                stale = hs_status == 'COMPLETED' and row[2] != 'completed'
                print(
                    '    task', row[0], 'local', row[2],
                    'engagement_status', hs_status,
                    'STALE' if stale else '',
                )
    return 0


if __name__ == '__main__':
    sys.exit(main())
