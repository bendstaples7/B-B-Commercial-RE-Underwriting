"""Mark analysis_complete on eligible leads and rescore for outreach UI testing.

Dry-run by default. Pass --apply to mutate the database.

Run from backend/:
    python scripts/seed_outreach_test_leads.py --email USER@example.com [--limit N] --apply
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger("seed_outreach_test_leads")

from app import create_app
from app.models.lead import Lead
from app.models.user import User
from app.services.lead_scoring_engine import LeadScoringEngine
from app.services.outreach_method_service import OUTREACH_ACTIONS


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", required=True, help="Owner email whose leads to seed")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max leads to update (0 = all eligible)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist updates and rescore (default is dry-run preview only)",
    )
    args = parser.parse_args()

    app = create_app("development")
    with app.app_context():
        from app import db

        user = User.query.filter_by(email=args.email).first()
        if not user:
            raise SystemExit(f"User not found: {args.email}")

        q = (
            Lead.query.filter_by(owner_user_id=user.user_id)
            .filter(Lead.has_phone.is_(True))
            .filter(Lead.has_email.is_(True))
            .filter(Lead.has_property_match.is_(True))
            .order_by(Lead.id)
        )
        if args.limit:
            leads = q.limit(args.limit).all()
        else:
            leads = q.all()

        if not leads:
            raise SystemExit("No eligible leads (phone + email + property match)")

        lead_ids = [lead.id for lead in leads]
        needs_complete = [lead.id for lead in leads if not lead.analysis_complete]

        logger.info(
            "Preview: %d eligible leads for %s (%d need analysis_complete)",
            len(lead_ids),
            args.email,
            len(needs_complete),
        )

        if not args.apply:
            logger.info("Dry-run only — re-run with --apply to update and rescore")
            return

        if needs_complete:
            logger.info(
                "Setting analysis_complete=true on %d / %d leads",
                len(needs_complete),
                len(lead_ids),
            )
            Lead.query.filter(Lead.id.in_(needs_complete)).update(
                {Lead.analysis_complete: True},
                synchronize_session=False,
            )
            db.session.commit()
        else:
            logger.info("All %d eligible leads already have analysis_complete", len(lead_ids))

        engine = LeadScoringEngine()
        n = engine.bulk_rescore(user.user_id, lead_ids=lead_ids)
        logger.info("Rescored %d leads in this batch", n)

        batch_q = Lead.query.filter(Lead.id.in_(lead_ids))
        for action in sorted(OUTREACH_ACTIONS):
            count = batch_q.filter(Lead.recommended_action == action).count()
            if count:
                logger.info("  %s: %d", action, count)

        with_method = batch_q.filter(Lead.recommended_contact_method.isnot(None)).count()
        logger.info("Batch leads with recommended_contact_method: %d", with_method)

        sample = (
            batch_q.filter(Lead.recommended_contact_method.isnot(None))
            .order_by(Lead.id)
            .limit(5)
            .all()
        )
        for lead in sample:
            logger.info(
                "  id=%s action=%s method=%s score=%s warm=%s",
                lead.id,
                lead.recommended_action,
                lead.recommended_contact_method,
                lead.lead_score,
                lead.is_warm,
            )


if __name__ == "__main__":
    main()
