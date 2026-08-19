"""Add contacts.name_locked and owner_name_changed timeline events.

Revision ID: name_lock_20260819
Revises: heal_depri_20260819
Create Date: 2026-08-19
"""
from alembic import op


revision = 'name_lock_20260819'
down_revision = 'heal_depri_20260819'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE contacts "
        "ADD COLUMN IF NOT EXISTS name_locked BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TYPE timeline_event_type_enum "
        "ADD VALUE IF NOT EXISTS 'owner_name_changed'"
    )


def downgrade():
    op.execute("ALTER TABLE contacts DROP COLUMN IF EXISTS name_locked")
