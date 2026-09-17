"""Cancel undated rematch tasks left from staged-batch enqueue.

Revision ID: mail_stg_20260910
Revises: gen_own_20260910
Create Date: 2026-09-10

Enqueue no longer creates an undated ``Add to next mailer`` LeadTask while a
lead is staged — queue membership + ``mail_queue_status`` are the source of
truth. Rematch tasks are created on send (dated +90d).

This heal cancels leftover open undated rematch rows (and their CRM mirrors)
so command-center Open Tasks stop showing phantom staged work.

Identity matches ``is_mail_follow_up_task``: workflow key or canonical rematch
titles — not bare ``task_type = add_to_mail_batch`` (prep/manual mail tasks
share that type).
"""
from __future__ import annotations

from datetime import datetime

from alembic import op
import sqlalchemy as sa

revision = 'mail_stg_20260910'
down_revision = 'gen_own_20260910'
branch_labels = None
depends_on = None

# Keep in sync with mail_task_lifecycle_service.FOLLOW_UP_AFTER_MAIL_TITLE_RE
# / MAIL_REMATCH_WORKFLOW_KEY — rematch identity only (not all mail-batch tasks).
_REMATCH_WHERE = """
    status = 'open'
    AND due_date IS NULL
    AND (
      workflow_key = 'mail_rematch_cadence'
      OR title ILIKE '%add to next mailer%'
      OR title ILIKE '%follow up after mail%'
    )
"""


def upgrade() -> None:
    conn = op.get_bind()
    now = datetime.utcnow()

    rows = conn.execute(
        sa.text(
            f"""
            SELECT id, lead_id, mirror_task_id
            FROM lead_tasks
            WHERE {_REMATCH_WHERE}
            """
        )
    ).fetchall()
    if not rows:
        return

    task_ids = [row[0] for row in rows]
    lead_ids = sorted({row[1] for row in rows if row[1] is not None})
    mirror_ids = {row[2] for row in rows if row[2] is not None}

    conn.execute(
        sa.text(
            """
            UPDATE lead_tasks
            SET status = 'cancelled',
                completed_at = :now
            WHERE id IN :ids
            """
        ).bindparams(sa.bindparam('ids', expanding=True)),
        {'now': now, 'ids': task_ids},
    )

    # Linked mirrors (mirror_task_id set on the rematch LeadTask).
    if mirror_ids:
        conn.execute(
            sa.text(
                """
                UPDATE tasks
                SET status = 'cancelled',
                    updated_at = :now
                WHERE id IN :ids
                  AND status IN ('open', 'overdue')
                """
            ).bindparams(sa.bindparam('ids', expanding=True)),
            {'now': now, 'ids': sorted(mirror_ids)},
        )

    # Legacy rematch rows with no mirror_task_id — cancel open CRM mirrors by
    # lead + rematch title identity, skipping any mirror still linked from
    # another open LeadTask (safe dedupe).
    if lead_ids:
        conn.execute(
            sa.text(
                """
                UPDATE tasks AS t
                SET status = 'cancelled',
                    updated_at = :now
                WHERE t.lead_id IN :lead_ids
                  AND t.status IN ('open', 'overdue')
                  AND (
                    t.title ILIKE '%add to next mailer%'
                    OR t.title ILIKE '%follow up after mail%'
                  )
                  AND NOT EXISTS (
                    SELECT 1
                    FROM lead_tasks AS lt
                    WHERE lt.mirror_task_id = t.id
                      AND lt.status = 'open'
                  )
                """
            ).bindparams(sa.bindparam('lead_ids', expanding=True)),
            {'now': now, 'lead_ids': lead_ids},
        )


def downgrade() -> None:
    # Irreversible data heal — cancelled rematch rows are not reopened.
    pass
