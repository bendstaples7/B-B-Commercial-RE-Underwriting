"""Add contacts.keep_on_gis and contact_kept timeline events.

Revision ID: keep_gis_20260819
Revises: name_lock_20260819
Create Date: 2026-08-19
"""
from alembic import op


revision = 'keep_gis_20260819'
down_revision = 'name_lock_20260819'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE contacts "
        "ADD COLUMN IF NOT EXISTS keep_on_gis BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TYPE timeline_event_type_enum "
        "ADD VALUE IF NOT EXISTS 'contact_kept'"
    )


def downgrade():
    op.execute("ALTER TABLE contacts DROP COLUMN IF EXISTS keep_on_gis")
