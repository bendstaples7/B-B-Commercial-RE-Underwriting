"""Cancel undated rematch tasks left from staged-batch enqueue.

Revision ID: mail_stg_20260910
Revises: gen_own_20260910
Create Date: 2026-09-10

Enqueue no longer creates an undated ``Add to next mailer`` LeadTask while a
lead is staged — queue membership + ``mail_queue_status`` are the source of
truth. Rematch tasks are created on send (dated +90d).

This heal cancels leftover open undated rematch rows (and their CRM mirrors)
so command-center Open Tasks stop showing phantom staged work.
"""
from __future__ import annotations

from datetime import datetime

from alembic import op
import sqlalchemy as sa

revision = 'mail_stg_20260910'
down_revision = 'gen_own_20260910'
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    now = datetime.utcnow()

    rows = conn.execute(
        sa.text(
            """
            SELECT id, mirror_task_id
            FROM lead_tasks
            WHERE status = 'open'
              AND due_date IS NULL
              AND (
                task_type = 'add_to_mail_batch'
                OR workflow_key = 'mail_rematch_cadence'
                OR title ILIKE '%add to next mailer%'
                OR title ILIKE '%follow up after mailer%'
              )
            """
        )
    ).fetchall()
    if not rows:
        return

    task_ids = [row[0] for row in rows]
    mirror_ids = [row[1] for row in rows if row[1] is not None]

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
            {'now': now, 'ids': mirror_ids},
        )


def downgrade() -> None:
    # Irreversible data heal — cancelled rematch rows are not reopened.
    pass
