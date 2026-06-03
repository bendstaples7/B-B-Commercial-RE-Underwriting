"""Add DuPage lead columns to leads table.

Revision ID: x3y4z5a6b7c8
Revises: w2x3y4z5a6b7
Create Date: 2026-06-01 00:00:00.000000

Changes:
  - Add source_type VARCHAR(50) nullable column to leads
  - Add tax_distress_data JSONB nullable column to leads
  - Add manual_priority INTEGER nullable column to leads
  - Add index ix_leads_source_type ON leads(source_type)
  - Add index ix_leads_owner_user_id_source_type ON leads(owner_user_id, source_type)

Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6
"""
from alembic import op

revision = 'x3y4z5a6b7c8'
down_revision = 'w2x3y4z5a6b7'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE leads
        ADD COLUMN IF NOT EXISTS source_type VARCHAR(50)
    """)
    op.execute("""
        ALTER TABLE leads
        ADD COLUMN IF NOT EXISTS tax_distress_data JSONB
    """)
    op.execute("""
        ALTER TABLE leads
        ADD COLUMN IF NOT EXISTS manual_priority INTEGER
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_leads_source_type
        ON leads(source_type)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_leads_owner_user_id_source_type
        ON leads(owner_user_id, source_type)
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_leads_owner_user_id_source_type")
    op.execute("DROP INDEX IF EXISTS ix_leads_source_type")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS manual_priority")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS tax_distress_data")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS source_type")
