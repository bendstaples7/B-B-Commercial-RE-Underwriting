"""merge pipeline_stage_config into main branch

Revision ID: z9a8b7c6d5e4
Revises: 5f9bc65a48ea, y4z5a6b7c8d9
Create Date: 2026-05-30 18:45:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'z9a8b7c6d5e4'
down_revision = ('y4z5a6b7c8d9', '5f9bc65a48ea')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
