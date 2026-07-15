"""Add priority score to multifamily deals.

Revision ID: q8r9s0t1u2v3
Revises: p7q8r9s0t1u2
"""
from alembic import op


revision = 'q8r9s0t1u2v3'
down_revision = 'p7q8r9s0t1u2'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE deals "
        "ADD COLUMN IF NOT EXISTS priority_score NUMERIC(10, 2) NOT NULL DEFAULT 0"
    )
    op.alter_column('deals', 'priority_score', server_default=None)


def downgrade():
    op.execute("ALTER TABLE deals DROP COLUMN IF EXISTS priority_score")
