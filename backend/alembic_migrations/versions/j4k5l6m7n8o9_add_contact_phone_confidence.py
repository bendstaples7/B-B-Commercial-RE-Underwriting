"""Add confidence tracking columns to contact_phones.

Revision ID: j4k5l6m7n8o9
Revises: i3j4k5l6m7n8
Create Date: 2026-06-26
"""
from alembic import op
import sqlalchemy as sa

revision = 'j4k5l6m7n8o9'
down_revision = 'i3j4k5l6m7n8'
branch_labels = None
depends_on = None

phone_source_enum = sa.Enum(
    'manual', 'hubspot_import', 'flat_backfill',
    name='contact_phone_source_enum',
)


def upgrade():
    phone_source_enum.create(op.get_bind(), checkfirst=True)
    op.add_column('contact_phones', sa.Column('notes', sa.Text(), nullable=True))
    op.add_column('contact_phones', sa.Column('confidence_score', sa.SmallInteger(), nullable=True))
    op.add_column('contact_phones', sa.Column('last_outcome', sa.String(length=30), nullable=True))
    op.add_column('contact_phones', sa.Column('last_called_at', sa.DateTime(), nullable=True))
    op.add_column(
        'contact_phones',
        sa.Column('source', phone_source_enum, nullable=True),
    )


def downgrade():
    op.drop_column('contact_phones', 'source')
    op.drop_column('contact_phones', 'last_called_at')
    op.drop_column('contact_phones', 'last_outcome')
    op.drop_column('contact_phones', 'confidence_score')
    op.drop_column('contact_phones', 'notes')
    phone_source_enum.drop(op.get_bind(), checkfirst=True)
