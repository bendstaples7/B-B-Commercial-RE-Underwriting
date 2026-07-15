"""Add deterministic LeadTask-to-Task mirror identity.

Revision ID: u0v1w2x3y4z5
Revises: t9u0v1w2x3y4
"""

from alembic import op
import sqlalchemy as sa


revision = 'u0v1w2x3y4z5'
down_revision = 't9u0v1w2x3y4'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        'ALTER TABLE lead_tasks '
        'ADD COLUMN IF NOT EXISTS mirror_task_id INTEGER'
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'fk_lead_tasks_mirror_task_id_tasks'
            ) THEN
                ALTER TABLE lead_tasks
                ADD CONSTRAINT fk_lead_tasks_mirror_task_id_tasks
                FOREIGN KEY (mirror_task_id)
                REFERENCES tasks(id)
                ON DELETE SET NULL;
            END IF;
        END
        $$;
        """
    )
    op.execute(
        'CREATE INDEX IF NOT EXISTS ix_lead_tasks_mirror_task_id '
        'ON lead_tasks(mirror_task_id)'
    )
    op.execute(sa.text(
        """
        UPDATE lead_tasks AS lt
        SET mirror_task_id = (
            SELECT MIN(t.id)
            FROM tasks AS t
            WHERE t.lead_id = lt.lead_id
              AND t.source = 'manual'
              AND t.title = lt.title
              AND t.task_type::text = lt.task_type::text
              AND CAST(t.due_date AS DATE) IS NOT DISTINCT FROM lt.due_date
        )
        WHERE (
            SELECT COUNT(*)
            FROM tasks AS t
            WHERE t.lead_id = lt.lead_id
              AND t.source = 'manual'
              AND t.title = lt.title
              AND t.task_type::text = lt.task_type::text
              AND CAST(t.due_date AS DATE) IS NOT DISTINCT FROM lt.due_date
        ) = 1
        """
    ))


def downgrade():
    op.execute('DROP INDEX IF EXISTS ix_lead_tasks_mirror_task_id')
    op.execute(
        'ALTER TABLE lead_tasks '
        'DROP CONSTRAINT IF EXISTS fk_lead_tasks_mirror_task_id_tasks'
    )
    op.execute(
        'ALTER TABLE lead_tasks DROP COLUMN IF EXISTS mirror_task_id'
    )
