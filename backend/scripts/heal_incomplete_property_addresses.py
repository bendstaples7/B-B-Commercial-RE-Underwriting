#!/usr/bin/env python3
"""Fill city/state/ZIP on street-only property addresses.

Usage:
  python scripts/heal_incomplete_property_addresses.py --dry-run
  python scripts/heal_incomplete_property_addresses.py --apply
  python scripts/heal_incomplete_property_addresses.py --apply --lead-id 11126
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
    parser.add_argument('--lead-id', type=int, default=None)
    parser.add_argument('--limit', type=int, default=500)
    args = parser.parse_args()

    from app import create_app
    from app.services.property_address_service import heal_incomplete_property_addresses

    app = create_app()
    with app.app_context():
        # Always start from id 0 so admin batches ignore the Beat Redis cursor.
        result = heal_incomplete_property_addresses(
            last_id=0 if args.lead_id is None else None,
            limit=args.limit,
            lead_id=args.lead_id,
            dry_run=bool(args.dry_run),
            commit=bool(args.apply),
            persist_cursor=False,
            # Dry-run is offline by default; apply may call Cook County GIS.
            try_gis=bool(args.apply),
            actor='heal_incomplete_property_addresses',
        )
        print(
            'mode=%s processed=%s completed=%s still_incomplete=%s errors=%s'
            % (
                'apply' if args.apply else 'dry-run',
                result.get('processed'),
                result.get('completed'),
                result.get('still_incomplete'),
                result.get('errors'),
            )
        )
        if args.dry_run:
            for preview in result.get('previews') or []:
                before = preview.get('before') or {}
                after = preview.get('after') or {}
                print(
                    '  lead=%s complete=%s sources=%s'
                    % (
                        preview.get('lead_id'),
                        preview.get('complete'),
                        preview.get('sources'),
                    )
                )
                print(
                    '    before street=%r city=%r state=%r zip=%r'
                    % (
                        before.get('property_street'),
                        before.get('property_city'),
                        before.get('property_state'),
                        before.get('property_zip'),
                    )
                )
                print(
                    '    after  street=%r city=%r state=%r zip=%r'
                    % (
                        after.get('property_street'),
                        after.get('property_city'),
                        after.get('property_state'),
                        after.get('property_zip'),
                    )
                )
        else:
            from app import db
            from app.models import Lead

            for lead_id in result.get('lead_ids') or []:
                lead = db.session.get(Lead, lead_id)
                if lead is None:
                    continue
                print(
                    '  lead=%s street=%r city=%r state=%r zip=%r'
                    % (
                        lead.id,
                        lead.property_street,
                        lead.property_city,
                        lead.property_state,
                        lead.property_zip,
                    )
                )
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
