"""Add contacts.name_locked and owner_name_changed timeline events.

Revision ID: name_lock_20260819
Revises: heal_depri_20260819
Create Date: 2026-08-19
"""
from alembic import op
import sqlalchemy as sa


revision = 'name_lock_20260819'
down_revision = 'heal_depri_20260819'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'contacts',
        sa.Column(
            'name_locked',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.execute(
        "ALTER TYPE timeline_event_type_enum "
        "ADD VALUE IF NOT EXISTS 'owner_name_changed'"
    )


def downgrade():
    op.drop_column('contacts', 'name_locked')
