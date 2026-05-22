"""merge sale_comp_nullable and socrata_cache branches

Revision ID: g7h8i9j0k1l2c
Revises: g7h8i9j0k1l2, g7h8i9j0k1l2b
Create Date: 2026-05-20 12:01:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'g7h8i9j0k1l2c'
down_revision = ('g7h8i9j0k1l2', 'g7h8i9j0k1l2b')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
