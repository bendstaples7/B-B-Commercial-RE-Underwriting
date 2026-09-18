"""Add meeting_logged value to timeline_event_type_enum.

Revision ID: mtg_log_20260918
Revises: hs_mtg_bf_20260918
Create Date: 2026-09-18

Native Action Center "Log Meeting" writes meeting_logged (parallel to
call_logged / email_logged). HubSpot imports remain hubspot_meeting.
"""
from alembic import op

revision = 'mtg_log_20260918'
down_revision = 'hs_mtg_bf_20260918'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        op.execute(
            "ALTER TYPE timeline_event_type_enum "
            "ADD VALUE IF NOT EXISTS 'meeting_logged'"
        )


def downgrade():
    # PostgreSQL does not support removing enum values; no-op on downgrade.
    pass
