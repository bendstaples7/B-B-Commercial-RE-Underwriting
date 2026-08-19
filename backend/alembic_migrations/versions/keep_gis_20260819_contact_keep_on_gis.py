"""Add contacts.keep_on_gis and contact_kept timeline events.

Revision ID: keep_gis_20260819
Revises: name_lock_20260819
Create Date: 2026-08-19
"""
from alembic import op
import sqlalchemy as sa


revision = 'keep_gis_20260819'
down_revision = 'name_lock_20260819'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'contacts',
        sa.Column(
            'keep_on_gis',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.execute(
        "ALTER TYPE timeline_event_type_enum "
        "ADD VALUE IF NOT EXISTS 'contact_kept'"
    )


def downgrade():
    op.drop_column('contacts', 'keep_on_gis')
