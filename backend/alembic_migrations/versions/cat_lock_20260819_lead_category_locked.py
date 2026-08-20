"""Lock lead_category when the user sets Residential/Commercial.

Revision ID: cat_lock_20260819
Revises: heal_own_20260819
Create Date: 2026-08-19

Downgrade drops the boolean column only. Postgres enum values
``category_changed`` / ``leads_merged`` are left in place (ADD VALUE is
not reversible without recreating the type).
"""
from alembic import op


revision = 'cat_lock_20260819'
down_revision = 'heal_own_20260819'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE leads "
        "ADD COLUMN IF NOT EXISTS lead_category_locked BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TYPE timeline_event_type_enum "
        "ADD VALUE IF NOT EXISTS 'category_changed'"
    )
    op.execute(
        "ALTER TYPE timeline_event_type_enum "
        "ADD VALUE IF NOT EXISTS 'leads_merged'"
    )


def downgrade():
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS lead_category_locked")
