"""Merge the two migration heads (lead status expansion + pipeline stage config).

Revision ID: z0a9b8c7d6e5
Revises: z9a8b7c6d5e4, s0t1u2v3w4x5
Create Date: 2026-06-09 09:10:00.000000
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'z0a9b8c7d6e5'
down_revision = ('z9a8b7c6d5e4', 's0t1u2v3w4x5')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass