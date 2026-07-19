#!/usr/bin/env python3
"""Consolidate same-building duplicate leads (dry-run or apply).

Uses the canonical duplicate sentinel — same path as Celery
``leads.run_duplicate_sentinel``. Not a one-off Davlin merge.

Examples (from backend/):

  python scripts/consolidate_duplicate_leads.py --dry-run
  python scripts/consolidate_duplicate_leads.py --apply --max-merges 200
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from env_loader import load_project_env

load_project_env()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview merges without writing',
    )
    mode.add_argument(
        '--apply',
        action='store_true',
        help='Commit clear auto-merges',
    )
    parser.add_argument(
        '--max-merges',
        type=int,
        default=200,
        help='Max loser rows to merge (default 200)',
    )
    args = parser.parse_args()

    from app import create_app
    from app.services.lead_dedup_service import run_duplicate_sentinel

    app = create_app()
    with app.app_context():
        stats = run_duplicate_sentinel(
            dry_run=bool(args.dry_run),
            max_merges=max(args.max_merges, 0),
        )
    print(json.dumps(stats, indent=2, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
