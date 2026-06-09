"""merge lead_scores and multifamily+om_intake branches

Revision ID: e5f6g7h8i9j0
Revises: b2c3d4e5f6g7, d4e5f6g7h8i9, d4e5f6g7h8i9b, e5f6g7h8i9j0b
Create Date: 2026-05-12 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'e5f6g7h8i9j0'
down_revision = ('d4e5f6g7h8i9b', 'e5f6g7h8i9j0b')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
