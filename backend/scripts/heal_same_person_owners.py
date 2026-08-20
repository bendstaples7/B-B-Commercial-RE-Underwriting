#!/usr/bin/env python3
"""Consolidate same-person owner fragments on a lead (e.g. Sam name variants).

Keeps the outreach contact that owns the confirmed dialed phone, merges other
phones onto it, demotes duplicate owner links to former_owner, refreshes scoring.

Usage:
  python scripts/heal_same_person_owners.py --lead-id 4490 --dry-run
  python scripts/heal_same_person_owners.py --lead-id 4490 --apply
  python scripts/heal_same_person_owners.py --lead-id 4490 --apply --keep-phone-digits 7732715525
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
    parser.add_argument('--lead-id', type=int, required=True)
    parser.add_argument('--keep-phone-digits', default=None)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--dry-run', action='store_true')
    group.add_argument('--apply', action='store_true')
    args = parser.parse_args()

    from app import create_app
    from app.services.contact_service import ContactService

    # Match Deploy / production: avoid development auto-migrate side effects.
    os.environ['FLASK_ENV'] = 'production'
    app = create_app('production')
    with app.app_context():
        result = ContactService().heal_same_person_owner_cluster(
            args.lead_id,
            apply=bool(args.apply),
            keep_phone_digits=args.keep_phone_digits,
            refresh_scoring=bool(args.apply),
            bump_call_task=bool(args.apply),
            commit=bool(args.apply),
        )
        print(json.dumps(result, default=str))
        if not args.apply:
            print('Dry-run only — pass --apply to write')


if __name__ == '__main__':
    main()
