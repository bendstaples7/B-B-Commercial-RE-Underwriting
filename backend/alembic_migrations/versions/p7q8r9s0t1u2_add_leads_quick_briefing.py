"""Add leads.quick_briefing JSONB for persisted CC briefings.

Revision ID: p7q8r9s0t1u2
Revises: o6p7q8r9s0t1
Create Date: 2026-07-14

Stores the latest on-demand Gemini quick briefing so Command Center can reload
it and Refresh can revise from the prior version.
"""
from alembic import op


revision = 'p7q8r9s0t1u2'
down_revision = 'o6p7q8r9s0t1'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE leads
        ADD COLUMN IF NOT EXISTS quick_briefing JSONB
    """)


def downgrade():
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS quick_briefing")
