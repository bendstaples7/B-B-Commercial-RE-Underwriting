#!/usr/bin/env python3
"""Heal skip_trace leads that already have a complete owner mailing address.

By default only system ``awaiting_skip_trace_handoff`` rows (and orphan
``needs_skip_trace`` with no open skip tasks) are healed. Pass
``--include-manual`` to also clear intentional skip-trace research tasks.

Usage:
  cd backend
  python scripts/heal_mailable_skip_trace_leads.py --dry-run
  python scripts/heal_mailable_skip_trace_leads.py --apply
  python scripts/heal_mailable_skip_trace_leads.py --apply --limit 50
  python scripts/heal_mailable_skip_trace_leads.py --apply --lead-id 4239
  python scripts/heal_mailable_skip_trace_leads.py --apply --include-manual
"""
from __future__ import annotations

import argparse
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND_DIR)

from env_loader import load_project_env

load_project_env()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--apply', action='store_true')
    parser.add_argument('--limit', type=int, default=None)
    parser.add_argument('--lead-id', type=int, default=None, help='Heal a single lead')
    parser.add_argument('--no-rescore', action='store_true')
    parser.add_argument(
        '--include-manual',
        action='store_true',
        help='Also heal leads with non-system open skip_trace_owner tasks',
    )
    args = parser.parse_args()

    from app import create_app, db
    from app.models.lead import Lead
    from app.services.skip_trace_mailable_heal_service import SkipTraceMailableHealService

    app = create_app()
    with app.app_context():
        svc = SkipTraceMailableHealService()
        if args.lead_id is not None:
            lead = db.session.get(Lead, args.lead_id)
            if lead is None:
                print(f'lead_id={args.lead_id} not found')
                return 1
            if args.apply:
                result = svc.heal_lead(
                    lead,
                    commit=True,
                    rescore=not args.no_rescore,
                    include_manual=args.include_manual,
                )
                print(result)
                return 0 if result.get('healed') or result.get('needs_cleared') else 2
            eligible = svc.is_heal_candidate(
                lead, include_manual=args.include_manual,
            )
            print({
                'lead_id': lead.id,
                'dry_run': True,
                'eligible': eligible,
                'lead_status': lead.lead_status,
                'needs_skip_trace': lead.needs_skip_trace,
                'mailing_address': lead.mailing_address,
                'property_street': lead.property_street,
            })
            return 0 if eligible else 2

        summary = svc.heal_all(
            commit=bool(args.apply),
            limit=args.limit,
            rescore=not args.no_rescore,
            include_manual=args.include_manual,
        )
        print(
            'mode=%s candidates=%s healed=%s promoted=%s needs_cleared=%s'
            % (
                summary['mode'],
                summary['candidate_count'],
                summary['healed_count'],
                summary['promoted_count'],
                summary.get('needs_cleared_count', 0),
            )
        )
        for row in summary['results'][:50]:
            print(
                '  lead_id=%s street=%s mail=%s status=%s handoffs=%s '
                'promoted=%s needs_cleared=%s'
                % (
                    row.get('lead_id'),
                    (row.get('property_street') or '')[:40],
                    (row.get('mailing_address') or '')[:40],
                    row.get('lead_status'),
                    row.get('open_handoffs', len(row.get('completed_task_ids') or [])),
                    row.get('promoted', False),
                    row.get('needs_cleared', False),
                )
            )
        if summary['candidate_count'] > 50:
            print(f"  ... and {summary['candidate_count'] - 50} more")
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
