"""Backfill task_completed timeline rows for HubSpot-completed LeadTasks.

HubSpot inbound task sync historically updated LeadTask/Task without writing
LeadTimelineEntry. This script inserts missing ``task_completed`` rows.

Dry-run by default. Pass --apply to mutate the database.

Run from backend/:
    python scripts/backfill_hubspot_task_completed_timeline.py [--apply] [--limit N] [--lead-id ID]
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
logger = logging.getLogger('backfill_hubspot_task_completed_timeline')

from app import create_app
from app.services.hubspot_task_completion_service import (
    backfill_missing_hubspot_task_completed_timelines,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description='Backfill missing HubSpot task_completed timeline entries',
    )
    parser.add_argument(
        '--apply',
        action='store_true',
        help='Persist changes (default is dry-run)',
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=500,
        help='Max LeadTasks to scan per run (default: 500)',
    )
    parser.add_argument('--lead-id', type=int, default=None, help='Restrict to one lead')
    args = parser.parse_args(argv)

    app = create_app()
    with app.app_context():
        result = backfill_missing_hubspot_task_completed_timelines(
            dry_run=not args.apply,
            limit=args.limit,
            lead_id=args.lead_id,
        )
        logger.info(
            'done scanned=%s missing=%s applied=%s skipped=%s dry_run=%s',
            result['scanned'],
            result['missing'],
            result['applied'],
            result['skipped'],
            result['dry_run'],
        )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
