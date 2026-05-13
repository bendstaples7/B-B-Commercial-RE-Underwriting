"""add rentcast_cache table

Revision ID: f6g7h8i9j0k1
Revises: e5f6g7h8i9j0
Create Date: 2026-05-12 18:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'f6g7h8i9j0k1'
down_revision = 'e5f6g7h8i9j0'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'rentcast_cache',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('address_key', sa.String(length=500), nullable=False),
        sa.Column('unit_type_label', sa.String(length=100), nullable=False),
        sa.Column('bedrooms', sa.Integer(), nullable=True),
        sa.Column('bathrooms', sa.Numeric(4, 1), nullable=True),
        sa.Column('square_footage', sa.Integer(), nullable=True),
        sa.Column('rent_estimate', sa.Numeric(14, 2), nullable=True),
        sa.Column('rent_range_low', sa.Numeric(14, 2), nullable=True),
        sa.Column('rent_range_high', sa.Numeric(14, 2), nullable=True),
        sa.Column('comparables_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('fetched_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'address_key', 'unit_type_label', 'bedrooms', 'bathrooms', 'square_footage',
            name='uq_rentcast_cache_key',
        ),
    )
    op.create_index('ix_rentcast_cache_address_fetched', 'rentcast_cache',
                    ['address_key', 'fetched_at'])


def downgrade():
    op.drop_index('ix_rentcast_cache_address_fetched', table_name='rentcast_cache')
    op.drop_table('rentcast_cache')
