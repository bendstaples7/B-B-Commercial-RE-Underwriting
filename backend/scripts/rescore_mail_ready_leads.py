"""Rescore leads still marked mail_ready so recent-sale rules update recommended_action.

Run from the backend/ directory:
    python scripts/rescore_mail_ready_leads.py [--dry-run]
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

from app import create_app, db  # noqa: E402
from app.models import Lead  # noqa: E402
from app.services.lead_scoring_engine import LeadScoringEngine  # noqa: E402

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description='Rescore mail_ready leads for recent-sale guardrails')
    parser.add_argument('--dry-run', action='store_true', help='List lead ids without rescoring')
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        lead_ids = [
            row.id
            for row in Lead.query.filter(Lead.recommended_action == 'mail_ready').order_by(Lead.id).all()
        ]
        logger.info('Found %d mail_ready leads', len(lead_ids))
        if args.dry_run:
            for lead_id in lead_ids[:20]:
                logger.info('  would rescore lead_id=%s', lead_id)
            if len(lead_ids) > 20:
                logger.info('  ... and %d more', len(lead_ids) - 20)
            return 0

        engine = LeadScoringEngine()
        rescored = engine.bulk_rescore('default', lead_ids=lead_ids)
        db.session.commit()
        logger.info('Rescored %d leads', rescored)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
