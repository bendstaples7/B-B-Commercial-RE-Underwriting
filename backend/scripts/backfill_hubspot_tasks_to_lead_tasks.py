"""Backfill open HubSpot-imported Task rows into canonical LeadTask.

Copies open/overdue HubSpot ``tasks`` linked to a lead (via TaskAssociation or
direct lead_id) into ``lead_tasks`` when no LeadTask yet exists for that
``hubspot_task_id``.

Dry-run by default. Pass --apply to mutate the database.

Run from backend/:
    python scripts/backfill_hubspot_tasks_to_lead_tasks.py [--apply] [--limit N]
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
logger = logging.getLogger('backfill_hubspot_tasks_to_lead_tasks')

from app import create_app, db
from app.models import LeadTask
from app.models.task import Task
from app.models.task_association import TaskAssociation
from app.services.lead_task_service import LeadTaskService


def _candidate_rows(limit: int | None) -> list[tuple[Task, int]]:
    """Return (Task, lead_id) pairs for open HubSpot tasks linked to a lead."""
    via_assoc = (
        db.session.query(Task, TaskAssociation.target_id)
        .join(TaskAssociation, TaskAssociation.task_id == Task.id)
        .filter(
            TaskAssociation.target_type == 'lead',
            Task.status.in_(['open', 'overdue']),
            Task.source == 'hubspot_import',
            Task.hubspot_task_id.isnot(None),
        )
        .all()
    )
    via_direct = (
        db.session.query(Task, Task.lead_id)
        .filter(
            Task.lead_id.isnot(None),
            Task.status.in_(['open', 'overdue']),
            Task.source == 'hubspot_import',
            Task.hubspot_task_id.isnot(None),
        )
        .all()
    )

    seen_keys: set[tuple[str, int]] = set()
    rows: list[tuple[Task, int]] = []
    for task, lead_id in list(via_assoc) + list(via_direct):
        if lead_id is None or not task.hubspot_task_id:
            continue
        key = (str(task.hubspot_task_id), int(lead_id))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        rows.append((task, int(lead_id)))
        if limit is not None and len(rows) >= limit:
            break
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--apply',
        action='store_true',
        help='Persist LeadTask upserts (default is dry-run)',
    )
    parser.add_argument(
        '--limit',
        type=int,
        default=None,
        help='Max HubSpot task/lead pairs to consider (must be positive when set)',
    )
    args = parser.parse_args()

    if args.limit is not None and args.limit <= 0:
        parser.error('--limit must be a positive integer')

    app = create_app()
    with app.app_context():
        candidates = _candidate_rows(args.limit)
        logger.info('Found %s open HubSpot task/lead candidate(s)', len(candidates))
        print(f'Found {len(candidates)} open HubSpot task/lead candidate(s)', flush=True)

        created = 0
        skipped = 0
        svc = LeadTaskService()

        for task, lead_id in candidates:
            hs_id = str(task.hubspot_task_id)
            existing = LeadTask.query.filter_by(hubspot_task_id=hs_id).first()
            if existing is not None:
                skipped += 1
                continue

            logger.info(
                'Would upsert LeadTask for hubspot_task_id=%s lead_id=%s title=%r',
                hs_id,
                lead_id,
                task.title,
            )
            print(
                f'hubspot_task_id={hs_id} lead_id={lead_id} title={task.title!r}',
                flush=True,
            )

            if args.apply:
                svc.upsert_from_hubspot(
                    lead_id=lead_id,
                    hubspot_task_id=hs_id,
                    title=task.title or '(No Subject)',
                    status=task.status or 'open',
                    due_date=task.due_date,
                    commit=False,
                )
                created += 1

        if args.apply and created:
            db.session.commit()

        mode = 'applied' if args.apply else 'dry-run'
        logger.info(
            'Done (%s): created=%s skipped_existing=%s candidates=%s',
            mode,
            created,
            skipped,
            len(candidates),
        )
        print(
            f'Done ({mode}): created={created} skipped_existing={skipped} '
            f'candidates={len(candidates)}',
            flush=True,
        )


if __name__ == '__main__':
    main()
