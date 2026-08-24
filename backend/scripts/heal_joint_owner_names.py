#!/usr/bin/env python3
"""Optional bulk heal for live jammed owner names (A & B / A and B).

Alembic ``joint_own_20260821`` already heals this class on Deploy. Use this
script for dry-run counts or re-runs after new GIS imports.

Usage (from backend/):
  python scripts/heal_joint_owner_names.py --dry-run
  python scripts/heal_joint_owner_names.py --limit 500
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=None)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()

    from env_loader import load_project_env
    load_project_env()

    from app import create_app
    from app.models.lead import Lead
    from app.services.joint_owner_heal import heal_joint_owner_names
    from sqlalchemy import or_

    app = create_app()
    with app.app_context():
        if args.dry_run:
            query = Lead.query.filter(
                Lead.owner_first_name.isnot(None),
                or_(
                    Lead.owner_first_name.ilike('% and %'),
                    Lead.owner_first_name.ilike('% & %'),
                ),
            )
            if args.limit is not None:
                query = query.limit(args.limit)
            ids = [row.id for row in query.with_entities(Lead.id).all()]
            print(f'dry-run: {len(ids)} jammed primary owner rows would be scanned')
            for lead_id in ids[:20]:
                print(f'  lead_id={lead_id}')
            if len(ids) > 20:
                print(f'  … and {len(ids) - 20} more')
            return 0
        stats = heal_joint_owner_names(
            include_known_missing=True,
            heal_live_jammed=True,
            commit=True,
            limit=args.limit,
        )
        print(stats)
    return 1 if stats.get('errors') else 0


if __name__ == '__main__':
    raise SystemExit(main())
