"""Sync OLC address feedback (Corrected/Failed) for a mail campaign.

Dry-run by default (rolls back). Pass --apply to persist via
``MailCampaignService.sync_campaign_analytics``.

Run from backend/:
    python scripts/sync_olc_address_feedback.py --campaign-id 1
    python scripts/sync_olc_address_feedback.py --campaign-id 1 --apply
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

_backend_dir = Path(__file__).resolve().parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

from env_loader import load_project_env

load_project_env()

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger('sync_olc_address_feedback')


def _queue_snapshot() -> dict[str, int]:
    from app.models import MailQueueItem
    from sqlalchemy import func

    rows = (
        MailQueueItem.query
        .with_entities(MailQueueItem.status, func.count())
        .group_by(MailQueueItem.status)
        .all()
    )
    return {status: int(count) for status, count in rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign-id', type=int, required=True)
    parser.add_argument(
        '--apply',
        action='store_true',
        help='Persist analytics + address feedback (default is dry-run / rollback)',
    )
    args = parser.parse_args()

    from app import create_app, db
    from app.models import MailCampaign, MailQueueItem
    from app.services.mail_campaign_service import MailCampaignService

    app = create_app()
    with app.app_context():
        campaign = MailCampaign.query.get(args.campaign_id)
        if campaign is None:
            raise SystemExit(f'Campaign {args.campaign_id} not found')
        if not campaign.olc_order_id:
            raise SystemExit(f'Campaign {args.campaign_id} has no olc_order_id')

        before = _queue_snapshot()
        result = {
            'campaign_id': campaign.id,
            'status': campaign.status,
            'olc_order_id': campaign.olc_order_id,
            'apply': bool(args.apply),
            'queue_before': before,
        }

        if args.apply:
            updated = MailCampaignService().sync_campaign_analytics(campaign.id)
            summary = getattr(updated, '_address_feedback_summary', {}) or {}
            result['address_feedback'] = summary
            result['campaign_status_after'] = updated.status
            result['queue_after'] = _queue_snapshot()
        else:
            svc = MailCampaignService()
            client = svc._config_service.get_client(campaign.created_by)
            # Preview address apply only — no scoring refresh (avoids mid-sync commits)
            try:
                summary = svc._sync_order_address_statuses(
                    campaign, client, refresh_scoring=False,
                )
            except Exception as exc:
                db.session.rollback()
                result['error'] = f'{type(exc).__name__}: {exc}'
                print(json.dumps(result, indent=2, default=str), flush=True)
                raise SystemExit(1) from exc

            # Count how many queued rows were flipped in this session
            dirty_invalid = 0
            dirty_failed = 0
            for obj in db.session.dirty:
                if not isinstance(obj, MailQueueItem):
                    continue
                if obj.status == 'invalid_address':
                    dirty_invalid += 1
                elif obj.status == 'failed':
                    dirty_failed += 1

            result['address_feedback'] = summary
            result['session_queue_invalid_address'] = dirty_invalid
            result['session_queue_failed'] = dirty_failed
            db.session.rollback()
            result['queue_after'] = _queue_snapshot()
            result['note'] = 'Dry-run rolled back; pass --apply to persist'

    print(json.dumps(result, indent=2, default=str), flush=True)
    mode = 'APPLIED' if args.apply else 'DRY-RUN'
    logger.info('%s address feedback sync for campaign %s complete', mode, args.campaign_id)


if __name__ == '__main__':
    main()
