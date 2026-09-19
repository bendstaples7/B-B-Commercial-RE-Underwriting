"""Store source and why on manually captured contacts.

Revision ID: cap_src_20260919
Revises: act_mtg_20260919
Create Date: 2026-09-19
"""
from alembic import op


revision = 'cap_src_20260919'
down_revision = 'act_mtg_20260919'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS source VARCHAR(255)"
    )
    op.execute(
        "ALTER TABLE contacts ADD COLUMN IF NOT EXISTS capture_context TEXT"
    )


def downgrade():
    op.execute("ALTER TABLE contacts DROP COLUMN IF EXISTS capture_context")
    op.execute("ALTER TABLE contacts DROP COLUMN IF EXISTS source")
