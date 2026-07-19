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

from dotenv import load_dotenv

load_dotenv(os.path.join(BACKEND_DIR, '.env'))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--apply', action='store_true')
    parser.add_argument('--lead-id', type=int, default=None)
    parser.add_argument('--limit', type=int, default=500)
    args = parser.parse_args()

    from app import create_app, db
    from app.models import Lead
    from app.services.property_address_service import (
        complete_property_address,
        is_property_address_complete,
    )
    from sqlalchemy import or_

    app = create_app()
    with app.app_context():
        query = Lead.query.filter(
            Lead.property_street.isnot(None),
            Lead.property_street != '',
            or_(
                Lead.property_city.is_(None),
                Lead.property_city == '',
                Lead.property_state.is_(None),
                Lead.property_state == '',
                Lead.property_zip.is_(None),
                Lead.property_zip == '',
            ),
        ).order_by(Lead.id.asc())
        if args.lead_id is not None:
            query = query.filter(Lead.id == args.lead_id)
        leads = query.limit(args.limit).all()

        print('candidates=%s mode=%s' % (
            len(leads),
            'apply' if args.apply else 'dry-run',
        ))
        completed = 0
        still_incomplete = 0
        for lead in leads:
            before = (
                lead.property_street,
                lead.property_city,
                lead.property_state,
                lead.property_zip,
            )
            if args.dry_run:
                from app.services.property_address_service import (
                    complete_property_address_fields,
                )
                result = complete_property_address_fields(
                    lead.property_street,
                    lead.property_city,
                    lead.property_state,
                    lead.property_zip,
                    try_gis=True,
                )
                print(
                    'lead=%s before=%r after=%r complete=%s sources=%s'
                    % (
                        lead.id,
                        before,
                        (
                            result.get('property_street'),
                            result.get('property_city'),
                            result.get('property_state'),
                            result.get('property_zip'),
                        ),
                        result.get('complete'),
                        result.get('sources'),
                    )
                )
                if result.get('complete'):
                    completed += 1
                else:
                    still_incomplete += 1
                continue

            result = complete_property_address(
                lead,
                try_gis=True,
                actor='heal_incomplete_property_addresses',
                commit=False,
            )
            print(
                'lead=%s changed=%s complete=%s city=%r zip=%r'
                % (
                    lead.id,
                    result.get('changed_fields'),
                    result.get('complete'),
                    lead.property_city,
                    lead.property_zip,
                )
            )
            if result.get('complete'):
                completed += 1
            else:
                still_incomplete += 1

        if args.apply:
            db.session.commit()
            for lead in leads:
                if is_property_address_complete(lead=lead):
                    try:
                        from app.services.lead_refresh import refresh_lead_scoring
                        refresh_lead_scoring(lead.id)
                    except Exception as exc:
                        print('rescore failed lead=%s: %s' % (lead.id, exc))

        print('done completed=%s still_incomplete=%s' % (completed, still_incomplete))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
