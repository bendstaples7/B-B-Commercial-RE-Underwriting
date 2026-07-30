"""Add assessor AKA situs columns on leads.

Revision ID: aka_situs_20260729
Revises: mail_omit_20260727
Create Date: 2026-07-29
"""
from alembic import op

revision = 'aka_situs_20260729'
down_revision = 'mail_omit_20260727'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE leads
        ADD COLUMN IF NOT EXISTS assessor_aka_street VARCHAR(500)
    """)
    op.execute("""
        ALTER TABLE leads
        ADD COLUMN IF NOT EXISTS assessor_aka_city VARCHAR(100)
    """)
    op.execute("""
        ALTER TABLE leads
        ADD COLUMN IF NOT EXISTS assessor_aka_state VARCHAR(50)
    """)
    op.execute("""
        ALTER TABLE leads
        ADD COLUMN IF NOT EXISTS assessor_aka_zip VARCHAR(20)
    """)


def downgrade():
    op.execute('ALTER TABLE leads DROP COLUMN IF EXISTS assessor_aka_zip')
    op.execute('ALTER TABLE leads DROP COLUMN IF EXISTS assessor_aka_state')
    op.execute('ALTER TABLE leads DROP COLUMN IF EXISTS assessor_aka_city')
    op.execute('ALTER TABLE leads DROP COLUMN IF EXISTS assessor_aka_street')
