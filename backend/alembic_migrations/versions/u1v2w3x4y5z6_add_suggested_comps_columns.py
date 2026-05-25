"""add_suggested_comps_columns

Adds is_suggested, is_dismissed, and out_of_range columns to sale_comps.
These support the "suggested comps" workflow where AI-fetched comps are
held for user review before being included in rollup statistics.

Revision ID: u1v2w3x4y5z6
Revises: t0u1v2w3x4y5
Create Date: 2026-05-24 00:00:00.000000
"""
from alembic import op


revision = 'u1v2w3x4y5z6'
down_revision = 't0u1v2w3x4y5'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE sale_comps
        ADD COLUMN IF NOT EXISTS is_suggested BOOLEAN NOT NULL DEFAULT FALSE
    """)
    op.execute("""
        ALTER TABLE sale_comps
        ADD COLUMN IF NOT EXISTS is_dismissed BOOLEAN NOT NULL DEFAULT FALSE
    """)
    op.execute("""
        ALTER TABLE sale_comps
        ADD COLUMN IF NOT EXISTS out_of_range BOOLEAN NOT NULL DEFAULT FALSE
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_sale_comps_suggested
        ON sale_comps (deal_id, is_suggested, is_dismissed)
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_sale_comps_suggested")
    op.execute("ALTER TABLE sale_comps DROP COLUMN IF EXISTS out_of_range")
    op.execute("ALTER TABLE sale_comps DROP COLUMN IF EXISTS is_dismissed")
    op.execute("ALTER TABLE sale_comps DROP COLUMN IF EXISTS is_suggested")
