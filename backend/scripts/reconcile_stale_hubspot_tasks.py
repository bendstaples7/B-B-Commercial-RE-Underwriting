"""Sweep HubSpot-imported tasks that are open locally but completed in HubSpot.

Dry-run by default — pass --apply to reconcile via live CRM v3 sync.
"""
from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

load_dotenv()


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Find and fix stale open HubSpot-imported tasks.',
    )
    parser.add_argument(
        '--apply',
        action='store_true',
        help='Apply fixes via live CRM v3 sync (default is dry-run).',
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=500,
        help='Max tasks to scan (default 500).',
    )
    args = parser.parse_args()

    from app import create_app
    from app.services.hubspot_deal_sync_service import HubSpotDealSyncService

    app = create_app()
    with app.app_context():
        stats = HubSpotDealSyncService().sweep_stale_open_hubspot_tasks(
            dry_run=not args.apply,
            limit=args.limit,
        )
        print(stats)
        if stats['stale_found'] and not args.apply:
            print('Re-run with --apply to fix stale tasks via live CRM v3 sync.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
