"""Add leads.asking_price for Command Center seller asking price.

Revision ID: ask_prc_20260918
Revises: mail_sub_20260910
Create Date: 2026-09-18

User-entered seller asking price, distinct from assessor ``assessed_value``
(Est. value) and from multifamily OM intake asking_price.
"""
from alembic import op

revision = 'ask_prc_20260918'
down_revision = 'mail_sub_20260910'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        'ALTER TABLE leads ADD COLUMN IF NOT EXISTS asking_price DOUBLE PRECISION'
    )


def downgrade():
    op.execute(
        'ALTER TABLE leads DROP COLUMN IF EXISTS asking_price'
    )
