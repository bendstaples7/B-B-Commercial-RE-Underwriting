"""Add property address timeline event types.

Revision ID: addr_tl_20260719
Revises: stale_uq_20260717
Create Date: 2026-07-19 00:00:00.000000

Changes:
  - Add 'property_address_incomplete' and 'property_address_completed'
    to timeline_event_type_enum
"""
from alembic import op

revision = 'addr_tl_20260719'
down_revision = 'stale_uq_20260717'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TYPE timeline_event_type_enum "
        "ADD VALUE IF NOT EXISTS 'property_address_incomplete'"
    )
    op.execute(
        "ALTER TYPE timeline_event_type_enum "
        "ADD VALUE IF NOT EXISTS 'property_address_completed'"
    )


def downgrade():
    # PostgreSQL does not support removing enum values; no-op on downgrade.
    pass
