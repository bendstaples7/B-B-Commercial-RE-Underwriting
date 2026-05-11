"""add socrata cache tables

Revision ID: g7h8i9j0k1l2
Revises: fd5451087f07
Create Date: 2026-05-20 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'g7h8i9j0k1l2'
down_revision = 'fd5451087f07'
branch_labels = None
depends_on = None


def upgrade():
    # 1. parcel_universe_cache
    op.create_table(
        'parcel_universe_cache',
        sa.Column('pin', sa.String(14), nullable=False),
        sa.Column('lat', sa.Numeric(10, 7), nullable=True),
        sa.Column('lon', sa.Numeric(10, 7), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('pin'),
    )
    op.create_index('ix_parcel_universe_lat_lon', 'parcel_universe_cache', ['lat', 'lon'])

    # 2. parcel_sales_cache
    op.create_table(
        'parcel_sales_cache',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('pin', sa.String(14), nullable=False),
        sa.Column('sale_date', sa.Date(), nullable=True),
        sa.Column('sale_price', sa.Numeric(14, 2), nullable=True),
        # 'class' is a Python reserved word; the ORM attribute is class_ but the
        # physical DB column must be named 'class' to match the model definition:
        #   class_ = db.Column('class', db.String(10), nullable=True)
        sa.Column('class', sa.String(10), nullable=True),
        sa.Column('sale_type', sa.String(50), nullable=True),
        sa.Column('is_multisale', sa.Boolean(), nullable=True),
        sa.Column('sale_filter_less_than_10k', sa.Boolean(), nullable=True),
        sa.Column('sale_filter_deed_type', sa.Boolean(), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_parcel_sales_pin_sale_date', 'parcel_sales_cache', ['pin', 'sale_date'])
    op.create_index('ix_parcel_sales_sale_date', 'parcel_sales_cache', ['sale_date'])

    # 3. improvement_characteristics_cache
    op.create_table(
        'improvement_characteristics_cache',
        sa.Column('pin', sa.String(14), nullable=False),
        sa.Column('bldg_sf', sa.Integer(), nullable=True),
        sa.Column('beds', sa.Integer(), nullable=True),
        sa.Column('fbath', sa.Numeric(4, 1), nullable=True),
        sa.Column('hbath', sa.Numeric(4, 1), nullable=True),
        sa.Column('age', sa.Integer(), nullable=True),
        sa.Column('ext_wall', sa.Integer(), nullable=True),
        sa.Column('apts', sa.Integer(), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('pin'),
    )

    # 4. sync_log
    op.create_table(
        'sync_log',
        sa.Column('id', sa.Integer(), nullable=False, autoincrement=True),
        sa.Column('dataset_name', sa.String(100), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rows_upserted', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(10), nullable=False),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('running', 'success', 'failed')", name='ck_sync_log_status'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_sync_log_dataset_name', 'sync_log', ['dataset_name'])


def downgrade():
    op.drop_index('ix_sync_log_dataset_name', table_name='sync_log')
    op.drop_table('sync_log')
    op.drop_table('improvement_characteristics_cache')
    op.drop_index('ix_parcel_sales_sale_date', table_name='parcel_sales_cache')
    op.drop_index('ix_parcel_sales_pin_sale_date', table_name='parcel_sales_cache')
    op.drop_table('parcel_sales_cache')
    op.drop_index('ix_parcel_universe_lat_lon', table_name='parcel_universe_cache')
    op.drop_table('parcel_universe_cache')
