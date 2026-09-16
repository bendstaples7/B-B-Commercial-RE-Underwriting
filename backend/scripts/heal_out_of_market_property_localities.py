#!/usr/bin/env python3
"""Clear OSM ``Town of …`` / non-IL geocode false positives on property situs.

Usage (from backend/):
  python scripts/heal_out_of_market_property_localities.py --dry-run
  python scripts/heal_out_of_market_property_localities.py --apply
  python scripts/heal_out_of_market_property_localities.py --apply --lead-id 11134
"""
from __future__ import annotations

import argparse
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Heal out-of-market Nominatim property localities',
    )
    parser.add_argument('--dry-run', action='store_true', help='Preview only')
    parser.add_argument('--apply', action='store_true', help='Persist fixes')
    parser.add_argument('--lead-id', type=int, default=None)
    parser.add_argument('--limit', type=int, default=200)
    args = parser.parse_args()
    if not args.dry_run and not args.apply:
        parser.error('Pass --dry-run or --apply')

    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)

    from app import create_app
    from app.services.property_address_service import (
        heal_out_of_market_property_localities,
    )

    app = create_app()
    with app.app_context():
        summary = heal_out_of_market_property_localities(
            limit=args.limit,
            lead_id=args.lead_id,
            dry_run=bool(args.dry_run),
            commit=bool(args.apply),
            actor='heal_out_of_market_property_localities',
        )
        print(summary)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
