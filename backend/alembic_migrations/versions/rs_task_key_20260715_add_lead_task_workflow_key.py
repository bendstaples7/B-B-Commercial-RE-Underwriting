"""Add stable workflow identity to lead tasks.

Revision ID: rs_task_key_20260715
Revises: rs_hold_20260715
"""

from alembic import op


revision = 'rs_task_key_20260715'
down_revision = 'rs_hold_20260715'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE lead_tasks "
        "ADD COLUMN IF NOT EXISTS workflow_key VARCHAR(50)"
    )
    op.execute(
        "UPDATE lead_tasks "
        "SET workflow_key = 'recent_sale_hold' "
        "WHERE task_type = 'skip_trace_owner' "
        "AND title LIKE 'Recent-sale hold ended%'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_lead_tasks_workflow_key "
        "ON lead_tasks (workflow_key)"
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_lead_tasks_workflow_key")
    op.execute(
        "ALTER TABLE lead_tasks "
        "DROP COLUMN IF EXISTS workflow_key"
    )
