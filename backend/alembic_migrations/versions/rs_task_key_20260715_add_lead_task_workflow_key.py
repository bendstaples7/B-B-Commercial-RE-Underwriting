"""Add stable workflow identity to lead tasks.

Revision ID: rs_task_key_20260715
Revises: rs_hold_20260715
"""

from alembic import op
import sqlalchemy as sa


revision = 'rs_task_key_20260715'
down_revision = 'rs_hold_20260715'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'lead_tasks',
        sa.Column('workflow_key', sa.String(length=50), nullable=True),
    )
    op.execute(
        "UPDATE lead_tasks "
        "SET workflow_key = 'recent_sale_hold' "
        "WHERE task_type = 'skip_trace_owner' "
        "AND title LIKE 'Recent-sale hold ended%'"
    )
    op.create_index(
        'ix_lead_tasks_workflow_key',
        'lead_tasks',
        ['workflow_key'],
        unique=False,
    )


def downgrade():
    op.drop_index('ix_lead_tasks_workflow_key', table_name='lead_tasks')
    op.drop_column('lead_tasks', 'workflow_key')
