"""merge confidence_score and rentcast_cache branches

Revision ID: f6g7h8i9j0k1c
Revises: f6g7h8i9j0k1, f6g7h8i9j0k1b
Create Date: 2026-05-20 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'f6g7h8i9j0k1c'
down_revision = ('f6g7h8i9j0k1', 'f6g7h8i9j0k1b')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
