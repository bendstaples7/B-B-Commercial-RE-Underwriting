"""Replace hubspot_task_id unique index with (hubspot_task_id, lead_id).

Revision ID: k0l1m2n3o4p5
Revises: j9k0l1m2n3o4
Create Date: 2026-07-11

A HubSpot task can associate to multiple leads; each lead needs its own
LeadTask row. The previous single-column unique index prevented that.
"""
from alembic import op

revision = 'k0l1m2n3o4p5'
down_revision = 'j9k0l1m2n3o4'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("DROP INDEX IF EXISTS ix_lead_tasks_hubspot_task_id")
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_lead_tasks_hubspot_task_id_lead_id
        ON lead_tasks (hubspot_task_id, lead_id)
        WHERE hubspot_task_id IS NOT NULL
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_lead_tasks_hubspot_task_id_lead_id")
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_lead_tasks_hubspot_task_id
        ON lead_tasks (hubspot_task_id)
        WHERE hubspot_task_id IS NOT NULL
    """)
