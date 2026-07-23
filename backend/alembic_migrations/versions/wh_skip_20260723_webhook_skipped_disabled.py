"""Add skipped_disabled to webhook_log_status_enum.

Revision ID: wh_skip_20260723
Revises: heal_st_20260723
"""
from alembic import op

revision = 'wh_skip_20260723'
down_revision = 'heal_st_20260723'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TYPE webhook_log_status_enum "
        "ADD VALUE IF NOT EXISTS 'skipped_disabled'"
    )


def downgrade():
    # PostgreSQL cannot remove enum values safely; leave skipped_disabled in place.
    pass
