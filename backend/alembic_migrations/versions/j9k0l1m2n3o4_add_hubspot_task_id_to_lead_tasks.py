"""Add hubspot_task_id to lead_tasks for HubSpot task consolidation.

Revision ID: j9k0l1m2n3o4
Revises: i8j9k0l1m2n3
Create Date: 2026-07-11

LeadTask is the canonical open-task store for Command Center. HubSpot-imported
tasks are upserted here with hubspot_task_id so CC no longer UNIONs the CRM
``tasks`` table for lead-linked HubSpot work.
"""
from alembic import op
import sqlalchemy as sa

revision = 'j9k0l1m2n3o4'
down_revision = 'i8j9k0l1m2n3'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE lead_tasks
        ADD COLUMN IF NOT EXISTS hubspot_task_id VARCHAR(50)
    """)
    # Partial unique on hubspot_task_id alone (historical j9 state).
    # Successor k0l1m2n3o4p5 replaces this with (hubspot_task_id, lead_id).
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_lead_tasks_hubspot_task_id
        ON lead_tasks (hubspot_task_id)
        WHERE hubspot_task_id IS NOT NULL
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_lead_tasks_hubspot_task_id")
    op.execute("ALTER TABLE lead_tasks DROP COLUMN IF EXISTS hubspot_task_id")
