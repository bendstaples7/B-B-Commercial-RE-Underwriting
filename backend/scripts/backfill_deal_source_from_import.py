"""Backfill blank deal_source from CoStar-like imported source values.

Dry-run by default. Pass --apply to mutate the database.

Run from backend/:
    python scripts/backfill_deal_source_from_import.py
    python scripts/backfill_deal_source_from_import.py --apply
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

_backend_dir = Path(__file__).resolve().parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

from env_loader import load_project_env

load_project_env()

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger('backfill_deal_source_from_import')

from app import create_app
from app import db
from app.models.lead import Lead
from app.services.helpers.deal_source import normalize_imported_source_to_deal_source


def query_candidates(limit: int | None = None) -> list[Lead]:
    """Leads with blank deal_source and a non-empty source column."""
    q = (
        Lead.query.filter(
            db.or_(Lead.deal_source.is_(None), Lead.deal_source == ''),
            Lead.source.isnot(None),
            Lead.source != '',
        )
        .order_by(Lead.id.asc())
    )
    if limit is not None:
        q = q.limit(limit)
    return q.all()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--apply',
        action='store_true',
        help='Persist deal_source updates (default is preview only)',
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Optional max candidates to scan',
    )
    args = parser.parse_args()

    app = create_app('development')
    with app.app_context():
        candidates = query_candidates(limit=args.limit)
        updates: list[tuple[int, str, str]] = []
        for lead in candidates:
            mapped = normalize_imported_source_to_deal_source(lead.source)
            if mapped:
                updates.append((lead.id, lead.source or '', mapped))

        logger.info(
            "Scanned %d blank-deal_source leads; %d map to a deal_source value",
            len(candidates),
            len(updates),
        )
        print(
            f"Scanned {len(candidates)} blank-deal_source leads; "
            f"{len(updates)} map to a deal_source value",
            flush=True,
        )
        for lead_id, source, mapped in updates[:25]:
            logger.info("  lead %s: source=%r → deal_source=%r", lead_id, source, mapped)
        if len(updates) > 25:
            logger.info("  … and %d more", len(updates) - 25)

        if not updates:
            logger.info("Nothing to backfill.")
            print("Nothing to backfill.", flush=True)
            return

        if not args.apply:
            logger.info("Dry-run only — re-run with --apply to update")
            print("Dry-run only — re-run with --apply to update", flush=True)
            return

        try:
            updated = 0
            for lead_id, _source, mapped in updates:
                lead = db.session.get(Lead, lead_id)
                if lead is None:
                    continue
                if (lead.deal_source or '').strip():
                    continue
                lead.deal_source = mapped
                updated += 1
            db.session.commit()
            logger.info("Set deal_source on %d leads", updated)
            print(f"Set deal_source on {updated} leads", flush=True)
        except Exception:
            db.session.rollback()
            logger.exception("Backfill failed; no changes committed. Re-run to retry.")
            raise


if __name__ == '__main__':
    main()
