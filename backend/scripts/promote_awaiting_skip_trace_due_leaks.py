#!/usr/bin/env python3
"""Promote awaiting_skip_trace leads that leak into Today's Action into Skip Trace.

Selects leads in ``awaiting_skip_trace`` with an open dated task due today or
earlier, then calls ``SkipTraceEnqueue.promote_awaiting_skip_trace_due_leaks``.

Usage:
  python scripts/promote_awaiting_skip_trace_due_leaks.py --dry-run
  python scripts/promote_awaiting_skip_trace_due_leaks.py --apply
  python scripts/promote_awaiting_skip_trace_due_leaks.py --apply --limit 50
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
    parser.add_argument('--limit', type=int, default=500)
    args = parser.parse_args()

    from app import create_app, db
    from app.models import Lead
    from app.services.skip_trace_enqueue import SkipTraceEnqueue

    app = create_app()
    with app.app_context():
        service = SkipTraceEnqueue()
        result = service.promote_awaiting_skip_trace_due_leaks(
            actor='promote_awaiting_skip_trace_due_leaks_script',
            commit=bool(args.apply),
            limit=args.limit,
        )
        candidate_ids = result.get('candidate_lead_ids') or []
        print(
            'mode=%s candidates=%s promoted=%s'
            % (
                'apply' if args.apply else 'dry-run',
                result.get('candidate_lead_count', len(candidate_ids)),
                result.get('promoted_lead_count', 0),
            )
        )
        for lead_id in candidate_ids:
            lead = db.session.get(Lead, lead_id)
            street = (lead.property_street if lead else None) or ''
            status = lead.lead_status if lead else '?'
            print('  lead_id=%s status=%s street=%s' % (lead_id, status, street))
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
