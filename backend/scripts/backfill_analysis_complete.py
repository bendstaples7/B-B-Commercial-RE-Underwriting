"""Backfill analysis_complete for leads with completed analysis sessions.

Dry-run by default. Pass --apply to mutate the database and rescore.

Run from backend/:
    python scripts/backfill_analysis_complete.py [--apply]
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
logger = logging.getLogger('backfill_analysis_complete')

from app import create_app
from app import db
from app.models.lead import Lead
from app.services.analysis_completion_service import (
    ANALYSIS_COMPLETE_STEP,
    query_lead_ids_for_analysis_complete_backfill,
)
from app.services.lead_scoring_engine import LeadScoringEngine


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--apply',
        action='store_true',
        help='Persist analysis_complete=true and bulk rescore (default is preview only)',
    )
    args = parser.parse_args()

    app = create_app('development')
    with app.app_context():
        lead_ids = query_lead_ids_for_analysis_complete_backfill()
        logger.info(
            "Found %d leads with session at %s and analysis_complete=false",
            len(lead_ids),
            ANALYSIS_COMPLETE_STEP,
        )

        if not lead_ids:
            logger.info("Nothing to backfill.")
            return

        if not args.apply:
            logger.info("Dry-run only — re-run with --apply to update and rescore")
            logger.info("Sample lead IDs: %s", lead_ids[:20])
            return

        try:
            engine = LeadScoringEngine()
            rescored = engine.bulk_rescore('default', lead_ids=lead_ids)
            logger.info("Rescored %d leads", rescored)

            updated = (
                Lead.query.filter(Lead.id.in_(lead_ids))
                .update({Lead.analysis_complete: True}, synchronize_session=False)
            )
            db.session.commit()
            logger.info("Set analysis_complete=true on %d leads", updated)
        except Exception:
            db.session.rollback()
            logger.exception(
                "Backfill failed after rescoring; analysis_complete was not updated. "
                "Re-run the script to retry."
            )
            raise


if __name__ == '__main__':
    main()
