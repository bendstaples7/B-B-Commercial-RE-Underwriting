"""Add email_logged value to timeline_event_type_enum.

Revision ID: h2i3j4k5l6m7
Revises: g1h2i3j4k5l6
Create Date: 2026-06-24 00:00:00.000000

Changes:
  - Add 'email_logged' to timeline_event_type_enum for outbound email activity logs
"""
from alembic import op

revision = 'h2i3j4k5l6m7'
down_revision = 'g1h2i3j4k5l6'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TYPE timeline_event_type_enum ADD VALUE IF NOT EXISTS 'email_logged'"
    )


def downgrade():
    # PostgreSQL does not support removing enum values; no-op on downgrade.
    pass
