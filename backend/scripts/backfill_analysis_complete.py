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
from app.services.analysis_completion_service import ANALYSIS_COMPLETE_STEP
from app.services.lead_scoring_engine import LeadScoringEngine


def _eligible_lead_ids() -> list[int]:
    """Leads linked to a session that reached WEIGHTED_SCORING but flag is false."""
    from app.models import AnalysisSession

    rows = (
        db.session.query(Lead.id)
        .join(AnalysisSession, Lead.analysis_session_id == AnalysisSession.id)
        .filter(Lead.analysis_complete.is_(False))
        .all()
    )
    eligible: list[int] = []
    for (lead_id,) in rows:
        lead = db.session.get(Lead, lead_id)
        if lead is None or lead.analysis_session is None:
            continue
        completed = lead.analysis_session.completed_steps or []
        if ANALYSIS_COMPLETE_STEP in completed:
            eligible.append(lead_id)
    return eligible


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
        lead_ids = _eligible_lead_ids()
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

        updated = (
            Lead.query.filter(Lead.id.in_(lead_ids))
            .update({Lead.analysis_complete: True}, synchronize_session=False)
        )
        db.session.commit()
        logger.info("Set analysis_complete=true on %d leads", updated)

        engine = LeadScoringEngine()
        rescored = engine.bulk_rescore('default', lead_ids=lead_ids)
        logger.info("Rescored %d leads", rescored)


if __name__ == '__main__':
    main()
