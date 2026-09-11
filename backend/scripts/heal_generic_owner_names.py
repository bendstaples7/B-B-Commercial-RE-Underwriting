#!/usr/bin/env python3
"""Clear placeholder owner names (Taxpayer of, N/A, …) and unstage mail.

  python scripts/heal_generic_owner_names.py --dry-run
  python scripts/heal_generic_owner_names.py --apply
  python scripts/heal_generic_owner_names.py --apply --lead-id 2983
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--apply', action='store_true')
    parser.add_argument('--lead-id', type=int, default=None)
    parser.add_argument('--limit', type=int, default=None)
    parser.add_argument('--skip-rescore', action='store_true')
    args = parser.parse_args()

    from env_loader import load_project_env
    load_project_env()

    from app import create_app
    from app.services.generic_owner_heal_service import GenericOwnerHealService

    app = create_app()
    with app.app_context():
        summary = GenericOwnerHealService().heal_all(
            limit=args.limit,
            lead_id=args.lead_id,
            dry_run=args.dry_run,
            rescore=not args.skip_rescore,
        )
        print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
