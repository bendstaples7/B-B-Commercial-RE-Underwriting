"""Backfill: convert legacy post-mailer call follow-ups to quarterly rematch.

Finds open "Follow up after mailer" (and already-titled rematch) call tasks and
converts them to ``add_to_mail_batch`` due last_sent + 90 days. Cancels rematch
for suppressed / DNC leads.

Dry-run by default. Pass --apply to mutate the database.

Run from backend/:
    python scripts/backfill_mail_rematch_cadence.py [--apply] [--limit N]
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
logger = logging.getLogger('backfill_mail_rematch_cadence')

from sqlalchemy import or_

from app import create_app, db
from app.models import Lead, LeadTask
from app.services.last_mailed_service import get_last_mailed_at_by_lead_ids
from app.services.mail_task_lifecycle_service import (
    MAIL_REMATCH_TASK_TYPE,
    TERMINAL_MAIL_STOP_STATUSES,
    cancel_mail_rematch_tasks,
    convert_legacy_mail_follow_up_to_rematch,
    count_open_mail_rematch_tasks,
    is_mail_follow_up_task,
    mail_rematch_due_date,
    refresh_leads_after_mail_task_changes,
)


def _find_open_legacy_or_call_rematch_tasks(limit: int | None) -> list[LeadTask]:
    """Open rematch-identity tasks that still need conversion to add_to_mail_batch."""
    candidates: list[LeadTask] = []
    query = (
        LeadTask.query
        .filter(
            LeadTask.status == 'open',
            LeadTask.hubspot_task_id.is_(None),
            or_(
                LeadTask.title.ilike('%follow up after mail%'),
                LeadTask.title.ilike('%add to next mailer%'),
            ),
            or_(
                LeadTask.task_type.is_(None),
                LeadTask.task_type != MAIL_REMATCH_TASK_TYPE,
                ~LeadTask.title.ilike('%add to next mailer%'),
            ),
        )
        .order_by(LeadTask.id.asc())
    )
    if limit is not None:
        query = query.limit(limit)
    for task in query.all():
        if not is_mail_follow_up_task(task):
            continue
        # Already rematched (type + new title) — skip.
        if (
            task.task_type == MAIL_REMATCH_TASK_TYPE
            and task.title
            and 'add to next mailer' in task.title.lower()
        ):
            continue
        candidates.append(task)
        if limit is not None and len(candidates) >= limit:
            break
    return candidates


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--apply',
        action='store_true',
        help='Persist conversions (default is dry-run)',
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Max tasks to process (must be positive when set)',
    )
    args = parser.parse_args()

    if args.limit is not None and args.limit <= 0:
        parser.error('--limit must be a positive integer')

    app = create_app()
    with app.app_context():
        tasks = _find_open_legacy_or_call_rematch_tasks(args.limit)
        logger.info('Found %s open legacy mail follow-up task(s)', len(tasks))
        print(f'Found {len(tasks)} open legacy mail follow-up task(s)', flush=True)

        lead_ids = sorted({t.lead_id for t in tasks})
        last_mailed = get_last_mailed_at_by_lead_ids(lead_ids) if lead_ids else {}

        converted = 0
        cancelled = 0
        skipped = 0
        affected_leads: list[int] = []
        terminal_cancel_previewed_leads: set[int] = set()

        for task in tasks:
            lead = Lead.query.get(task.lead_id)
            if lead is None:
                skipped += 1
                logger.warning('Task %s: lead %s missing — skip', task.id, task.lead_id)
                continue

            status = (lead.lead_status or '').strip()
            if status in TERMINAL_MAIL_STOP_STATUSES:
                if args.apply:
                    n = cancel_mail_rematch_tasks(
                        lead.id,
                        actor='backfill_mail_rematch_cadence',
                        reason=f'terminal_status_{status}',
                    )
                    cancelled += n
                    if n:
                        affected_leads.append(lead.id)
                else:
                    n = (
                        0
                        if lead.id in terminal_cancel_previewed_leads
                        else count_open_mail_rematch_tasks(lead.id)
                    )
                    cancelled += n
                    if n:
                        terminal_cancel_previewed_leads.add(lead.id)
                        affected_leads.append(lead.id)
                logger.info(
                    'Lead %s task %s: %s rematch (status=%s)',
                    lead.id,
                    task.id,
                    'cancel' if args.apply else 'would cancel',
                    status,
                )
                print(
                    f'Lead {lead.id} task {task.id}: '
                    f'{"cancel" if args.apply else "would cancel"} '
                    f'(status={status})',
                    flush=True,
                )
                continue

            last_sent = last_mailed.get(lead.id)
            if last_sent is None:
                skipped += 1
                logger.warning(
                    'Lead %s task %s: no last_sent — skip',
                    lead.id,
                    task.id,
                )
                print(
                    f'Lead {lead.id} task {task.id}: skip (no send)',
                    flush=True,
                )
                continue
            due_preview = mail_rematch_due_date(last_sent, task.due_date)

            if args.apply:
                convert_legacy_mail_follow_up_to_rematch(
                    task,
                    lead,
                    last_sent_at=last_sent,
                    actor='backfill_mail_rematch_cadence',
                )
            converted += 1
            affected_leads.append(lead.id)

            logger.info(
                'Lead %s task %s: %s → add_to_mail_batch due %s (last_sent=%s)',
                lead.id,
                task.id,
                'convert' if args.apply else 'would convert',
                due_preview,
                last_sent.isoformat() if last_sent else None,
            )
            print(
                f'Lead {lead.id} task {task.id}: '
                f'{"convert" if args.apply else "would convert"} '
                f'due={due_preview} last_sent={last_sent}',
                flush=True,
            )

        if args.apply:
            try:
                db.session.commit()
            except Exception as exc:
                db.session.rollback()
                logger.exception('Failed to apply mail rematch backfill')
                print(f'Apply failed: {exc}', file=sys.stderr, flush=True)
                raise SystemExit(1) from exc
            unique_leads = sorted(set(affected_leads))
            refresh_leads_after_mail_task_changes(unique_leads)
            logger.info(
                'Applied: converted=%s cancelled=%s skipped=%s rescored=%s',
                converted,
                cancelled,
                skipped,
                len(unique_leads),
            )
            print(
                f'Applied: converted={converted} cancelled={cancelled} '
                f'skipped={skipped} rescored={len(unique_leads)}',
                flush=True,
            )
        else:
            logger.info(
                'Dry-run: would convert=%s would cancel=%s skipped=%s',
                converted,
                cancelled,
                skipped,
            )
            print(
                f'Dry-run: would convert={converted} would cancel={cancelled} '
                f'skipped={skipped}',
                flush=True,
            )


if __name__ == '__main__':
    main()
