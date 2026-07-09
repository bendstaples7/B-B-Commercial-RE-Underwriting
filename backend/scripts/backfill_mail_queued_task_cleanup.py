"""Backfill: complete stale outreach tasks for leads already in the mail batch.

Dry-run by default. Pass --apply to mutate the database.

Run from backend/:
    python scripts/backfill_mail_queued_task_cleanup.py [--apply] [--limit N]
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
logger = logging.getLogger('backfill_mail_queued_task_cleanup')

from app import create_app, db
from app.services.hubspot_task_completion_service import sync_pending_hubspot_completions
from app.services.mail_task_lifecycle_service import (
    complete_tasks_superseded_by_mail,
    find_mail_awaiting_lead_ids,
    refresh_leads_after_mail_task_changes,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--apply',
        action='store_true',
        help='Persist task completions (default is dry-run)',
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Max leads to process',
    )
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        lead_ids = find_mail_awaiting_lead_ids()
        if args.limit is not None:
            lead_ids = lead_ids[: args.limit]

        logger.info('Found %s mail-awaiting lead(s)', len(lead_ids))
        print(f'Found {len(lead_ids)} mail-awaiting lead(s)', flush=True)

        total_completed = 0
        hubspot_sync_ids: list[str] = []
        affected_leads: list[int] = []

        for lead_id in lead_ids:
            if args.apply:
                count, pending = complete_tasks_superseded_by_mail(
                    lead_id,
                    actor='backfill_mail_queued_task_cleanup',
                    commit=False,
                )
                if count:
                    affected_leads.append(lead_id)
                    total_completed += count
                    hubspot_sync_ids.extend(pending)
                    logger.info('Lead %s: completed %s superseded task(s)', lead_id, count)
                    print(f'Lead {lead_id}: completed {count} superseded task(s)', flush=True)
            else:
                from app.models import LeadTask
                from app.utils.call_completable_task import is_superseded_by_mail_task

                open_tasks = LeadTask.query.filter_by(lead_id=lead_id, status='open').all()
                would_complete = [
                    t for t in open_tasks
                    if is_superseded_by_mail_task(t.task_type, t.title)
                ]
                if would_complete:
                    affected_leads.append(lead_id)
                    total_completed += len(would_complete)
                    logger.info(
                        'Lead %s: would complete %s task(s): %s',
                        lead_id,
                        len(would_complete),
                        [t.title for t in would_complete],
                    )

        if args.apply and affected_leads:
            db.session.commit()
            sync_pending_hubspot_completions(hubspot_sync_ids)
            refresh_leads_after_mail_task_changes(affected_leads)

        mode = 'Applied' if args.apply else 'Dry-run'
        logger.info(
            '%s complete: %s lead(s) affected, %s task completion(s)',
            mode,
            len(affected_leads),
            total_completed,
        )
        print(
            f'{mode} complete: {len(affected_leads)} lead(s) affected, '
            f'{total_completed} task completion(s)',
            flush=True,
        )


if __name__ == '__main__':
    main()
