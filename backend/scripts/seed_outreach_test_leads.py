"""Mark analysis_complete on eligible leads and rescore for outreach UI testing.

Run from backend/:
    python scripts/seed_outreach_test_leads.py [--email USER_EMAIL] [--limit N]
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

DEFAULT_EMAIL = "ben.d.staples.7@gmail.com"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max leads to update (0 = all eligible)",
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
        if needs_complete:
            logger.info(
                "Setting analysis_complete=true on %d / %d leads for %s",
                len(needs_complete),
                len(lead_ids),
                args.email,
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
        logger.info("Rescored %d leads", n)

        outreach_actions = (
            "follow_up_now",
            "ready_for_outreach",
            "mail_ready",
            "call_ready",
            "review_now",
            "nurture",
        )
        for action in outreach_actions:
            count = (
                Lead.query.filter_by(owner_user_id=user.user_id)
                .filter(Lead.recommended_action == action)
                .count()
            )
            if count:
                logger.info("  %s: %d", action, count)

        with_method = (
            Lead.query.filter_by(owner_user_id=user.user_id)
            .filter(Lead.recommended_contact_method.isnot(None))
            .count()
        )
        logger.info("Leads with recommended_contact_method: %d", with_method)

        sample = (
            Lead.query.filter_by(owner_user_id=user.user_id)
            .filter(Lead.recommended_contact_method.isnot(None))
            .order_by(Lead.id)
            .limit(5)
            .all()
        )
        for lead in sample:
            logger.info(
                "  id=%s action=%s method=%s score=%s tier=%s warm=%s",
                lead.id,
                lead.recommended_action,
                lead.recommended_contact_method,
                lead.lead_score,
                getattr(lead, "score_tier", None),
                lead.is_warm,
            )


if __name__ == "__main__":
    main()
