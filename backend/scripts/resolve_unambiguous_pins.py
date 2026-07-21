#!/usr/bin/env python3
"""Resolve Cook County PINs only where an address has one assessor result.

Usage:
  python scripts/resolve_unambiguous_pins.py --dry-run
  python scripts/resolve_unambiguous_pins.py --apply --limit 250
  python scripts/resolve_unambiguous_pins.py --apply --start-id 5000 --limit 250
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
    parser.add_argument('--limit', type=int, default=100)
    parser.add_argument(
        '--start-id',
        type=int,
        default=0,
        help='Exclusive id to scan from (default 0 = top). Manual runs never '
             'move the hourly task cursor.',
    )
    args = parser.parse_args()

    from app import create_app
    from app.services.deploy_sync_policy import (
        _redis_client,
        release_redis_key_if_token,
        try_claim_redis_key,
    )
    from app.services.property_match_review_service import (
        RESOLVE_UNAMBIGUOUS_PINS_LOCK_KEY,
        PropertyMatchReviewService,
    )

    app = create_app()
    lock_token: str | None = None
    with app.app_context():
        # Mutating --apply must take the same lock as the hourly Celery task so
        # concurrent runs cannot approve the same PIN-empty rows twice.
        if args.apply:
            if _redis_client() is None:
                print('ERROR: Redis unavailable — refusing unlocked --apply', file=sys.stderr)
                return 1
            lock_token = try_claim_redis_key(
                RESOLVE_UNAMBIGUOUS_PINS_LOCK_KEY,
                ttl_seconds=50 * 60,
            )
            if not lock_token:
                print('ERROR: resolve_unambiguous_pins lock held — try again later', file=sys.stderr)
                return 1
        try:
            result = PropertyMatchReviewService().resolve_unambiguous_pins_batch(
                limit=args.limit,
                dry_run=bool(args.dry_run),
                actor='resolve_unambiguous_pins',
                last_id=max(0, args.start_id),
                persist_cursor=False,
            )
        finally:
            if lock_token:
                release_redis_key_if_token(
                    RESOLVE_UNAMBIGUOUS_PINS_LOCK_KEY, lock_token,
                )
    print(
        'mode=%s processed=%s resolved=%s ambiguous=%s no_match=%s incomplete=%s '
        'no_connector=%s errors=%s'
        % (
            'apply' if args.apply else 'dry-run',
            result['processed'],
            result['resolved'],
            result['skipped_ambiguous'],
            result['skipped_no_match'],
            result['skipped_incomplete'],
            result['skipped_no_connector'],
            result['errors'],
        )
    )
    for preview in result.get('previews') or []:
        print('  lead=%s pin=%s' % (preview['lead_id'], preview['pin']))
    return 1 if result['errors'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
