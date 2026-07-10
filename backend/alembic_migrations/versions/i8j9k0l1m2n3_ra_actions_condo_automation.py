"""RA actions + condo automation schema updates.

Revision ID: i8j9k0l1m2n3
Revises: h7i8j9k0l1m2
Create Date: 2026-07-09
"""
from alembic import op

revision = 'i8j9k0l1m2n3'
down_revision = 'h7i8j9k0l1m2'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS assessor_class VARCHAR(10)")

    op.execute("""
        ALTER TYPE timeline_event_type_enum ADD VALUE IF NOT EXISTS 'property_match_approved'
    """)
    op.execute("""
        ALTER TYPE timeline_event_type_enum ADD VALUE IF NOT EXISTS 'property_match_rejected'
    """)

    op.execute("""
        ALTER TYPE lead_task_type_enum ADD VALUE IF NOT EXISTS 'confirm_building_ownership'
    """)


def downgrade():
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS assessor_class")
    # PostgreSQL enums: new values cannot be removed safely without rebuild
