#!/usr/bin/env python3
"""Normalize incomplete / tabular owner mailing addresses.

Usage:
  python scripts/heal_incomplete_owner_mailings.py --dry-run
  python scripts/heal_incomplete_owner_mailings.py --apply
  python scripts/heal_incomplete_owner_mailings.py --apply --lead-id 11182
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
    from app.services.mailing_address_service import heal_incomplete_owner_mailings

    app = create_app()
    with app.app_context():
        result = heal_incomplete_owner_mailings(
            last_id=0 if args.lead_id is None else None,
            limit=args.limit,
            lead_id=args.lead_id,
            dry_run=bool(args.dry_run),
            commit=bool(args.apply),
            persist_cursor=False,
            actor='heal_incomplete_owner_mailings',
        )
        print(
            'mode=%s processed=%s healed=%s unchanged=%s still_blocked=%s '
            'errors=%s candidates_remaining=%s'
            % (
                'apply' if args.apply else 'dry-run',
                result.get('processed'),
                result.get('healed'),
                result.get('unchanged'),
                result.get('still_blocked'),
                result.get('errors'),
                result.get('candidates_remaining'),
            )
        )
        if args.dry_run:
            for preview in result.get('previews') or []:
                before = preview.get('before') or {}
                after = preview.get('after') or {}
                print(
                    '  lead=%s'
                    % preview.get('lead_id'),
                )
                print(
                    '    before street=%r city=%r state=%r zip=%r'
                    % (
                        before.get('mailing_address'),
                        before.get('mailing_city'),
                        before.get('mailing_state'),
                        before.get('mailing_zip'),
                    )
                )
                print(
                    '    after  street=%r city=%r state=%r zip=%r'
                    % (
                        after.get('mailing_address'),
                        after.get('mailing_city'),
                        after.get('mailing_state'),
                        after.get('mailing_zip'),
                    )
                )
        return 1 if result.get('errors') else 0


if __name__ == '__main__':
    raise SystemExit(main())
