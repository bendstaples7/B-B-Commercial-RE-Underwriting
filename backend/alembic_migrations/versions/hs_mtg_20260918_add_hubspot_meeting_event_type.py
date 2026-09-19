"""Add hubspot_meeting value to timeline_event_type_enum.

Revision ID: hs_mtg_20260918
Revises: qa_note_20260918
Create Date: 2026-09-18

HubSpot MEETING engagements were imported into hubspot_engagements but never
converted to Interactions or Command Center timeline rows. This revision adds
the event type; hs_mtg_bf_20260918 backfills existing meetings.
"""
from alembic import op

revision = 'hs_mtg_20260918'
down_revision = 'qa_note_20260918'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        op.execute(
            "ALTER TYPE timeline_event_type_enum "
            "ADD VALUE IF NOT EXISTS 'hubspot_meeting'"
        )


def downgrade():
    # PostgreSQL does not support removing enum values; no-op on downgrade.
    pass
