"""add confidence_score to valuation_results

Revision ID: f6g7h8i9j0k1
Revises: e5f6g7h8i9j0
Create Date: 2026-05-07 19:00:00.000000

Adds the ``confidence_score`` column to ``valuation_results``.
This column was introduced in Task 5 (adaptive confidence scoring) but
no migration was created at the time.  Defaults to NULL so existing rows
are unaffected.
"""
from alembic import op
import sqlalchemy as sa

revision = 'f6g7h8i9j0k1'
down_revision = 'e5f6g7h8i9j0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'valuation_results',
        sa.Column('confidence_score', sa.Float(), nullable=True),
    )


def downgrade():
    op.drop_column('valuation_results', 'confidence_score')
