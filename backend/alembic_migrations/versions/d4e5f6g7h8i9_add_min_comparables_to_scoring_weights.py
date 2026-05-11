"""add min_comparables to scoring_weights

Revision ID: d4e5f6g7h8i9
Revises: c3d4e5f6g7h8
Create Date: 2026-05-10 10:00:00.000000

Adds a user-configurable ``min_comparables`` column to the
``scoring_weights`` table.  The column stores the minimum number of
comparable sales a user wants before being warned during the
COMPARABLE_REVIEW workflow step.  Defaults to 10 (the production
standard) so existing rows are unaffected.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd4e5f6g7h8i9'
down_revision = 'c3d4e5f6g7h8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'scoring_weights',
        sa.Column(
            'min_comparables',
            sa.Integer(),
            nullable=False,
            server_default='10',
        ),
    )


def downgrade():
    op.drop_column('scoring_weights', 'min_comparables')
