#!/usr/bin/env python3
"""Unpark working leads silently copied to HubSpot Deprioritize.

Run outside Alembic (post-deploy / one-shot). Do not call from migrations.

Usage:
  python scripts/heal_working_deprioritize.py --dry-run
  python scripts/heal_working_deprioritize.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_SCRIPT_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = _SCRIPT_BACKEND if os.path.isdir(os.path.join(_SCRIPT_BACKEND, 'app')) else os.getcwd()
sys.path.insert(0, BACKEND_DIR)

from env_loader import load_project_env

load_project_env()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--dry-run', action='store_true')
    group.add_argument('--apply', action='store_true')
    args = parser.parse_args()

    from app import create_app
    from app.services.lead_status_service import (
        _has_manual_deprioritize,
        heal_working_deprioritize_leads,
        lead_has_active_outreach_work,
    )
    from app.models import Lead

    # Match Deploy / production: avoid development auto-migrate side effects.
    app = create_app('production')
    with app.app_context():
        if args.dry_run:
            candidates = 0
            parked = Lead.query.filter_by(lead_status='deprioritize').all()
            for lead in parked:
                if _has_manual_deprioritize(lead.id):
                    continue
                if not lead_has_active_outreach_work(lead.id):
                    continue
                candidates += 1
            print(json.dumps({
                'deprioritize_total': len(parked),
                'eligible_candidates': candidates,
                'dry_run': True,
            }))
            print('Dry-run only — pass --apply to write')
            return

        healed = heal_working_deprioritize_leads(
            commit=True,
            push_hubspot=False,
            recompute_action=True,
        )
        print(json.dumps({'healed': healed}, default=str))


if __name__ == '__main__':
    main()
