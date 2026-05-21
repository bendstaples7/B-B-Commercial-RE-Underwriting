"""Add lead_id and task_type to tasks table for CRM task unification.

Revision ID: p6q7r8s9t0u1
Revises: o5p6q7r8s9t0
Create Date: 2026-05-20 00:03:00.000000

Changes:
  - Add lead_id INTEGER REFERENCES leads(id) ON DELETE CASCADE to tasks (nullable)
  - Add task_type VARCHAR(50) to tasks (nullable) — CRM task type classification
  - Create index ix_tasks_lead_id on tasks(lead_id)
  - Backfill lead_id from task_associations WHERE target_type='lead'

Requirements: Simplification 1 — Merge lead_tasks into tasks
"""
from alembic import op


revision = 'p6q7r8s9t0u1'
down_revision = 'o5p6q7r8s9t0'
branch_labels = None
depends_on = None


def upgrade():
    # ------------------------------------------------------------------
    # 1. Add lead_id column (nullable FK to leads)
    # ------------------------------------------------------------------
    op.execute("""
        ALTER TABLE tasks
        ADD COLUMN IF NOT EXISTS lead_id INTEGER REFERENCES leads(id) ON DELETE CASCADE
    """)

    # ------------------------------------------------------------------
    # 2. Add task_type column (nullable VARCHAR for CRM classification)
    # ------------------------------------------------------------------
    op.execute("""
        ALTER TABLE tasks
        ADD COLUMN IF NOT EXISTS task_type VARCHAR(50)
    """)

    # ------------------------------------------------------------------
    # 3. Create index on tasks(lead_id)
    # ------------------------------------------------------------------
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_tasks_lead_id ON tasks(lead_id)
    """)

    # ------------------------------------------------------------------
    # 4. Backfill lead_id from task_associations WHERE target_type='lead'
    # ------------------------------------------------------------------
    op.execute("""
        UPDATE tasks
        SET lead_id = ta.target_id
        FROM task_associations ta
        WHERE ta.task_id = tasks.id
          AND ta.target_type = 'lead'
          AND tasks.lead_id IS NULL
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_tasks_lead_id")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS task_type")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS lead_id")
