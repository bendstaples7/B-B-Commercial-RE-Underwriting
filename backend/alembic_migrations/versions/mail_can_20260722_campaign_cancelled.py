"""Add cancelled to mail_campaign_status_enum.

Revision ID: mail_can_20260722
Revises: mail_cre_20260722
"""
from alembic import op

revision = 'mail_can_20260722'
down_revision = 'mail_cre_20260722'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TYPE mail_campaign_status_enum "
        "ADD VALUE IF NOT EXISTS 'cancelled'"
    )


def downgrade():
    # PostgreSQL cannot remove enum values safely; leave 'cancelled' in place.
    pass
