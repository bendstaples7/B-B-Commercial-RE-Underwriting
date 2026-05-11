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
    # All CREATE statements use IF NOT EXISTS so this migration is safe to run
    # even if the tables were already created by db.create_all() or a prior
    # partial migration run.

    # 1. parcel_universe_cache
    op.execute("""
        CREATE TABLE IF NOT EXISTS parcel_universe_cache (
            pin VARCHAR(14) NOT NULL,
            lat NUMERIC(10, 7),
            lon NUMERIC(10, 7),
            last_synced_at TIMESTAMP WITH TIME ZONE,
            PRIMARY KEY (pin)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_parcel_universe_lat_lon
        ON parcel_universe_cache (lat, lon)
    """)

    # 2. parcel_sales_cache
    op.execute("""
        CREATE TABLE IF NOT EXISTS parcel_sales_cache (
            id SERIAL NOT NULL,
            pin VARCHAR(14) NOT NULL,
            sale_date DATE,
            sale_price NUMERIC(14, 2),
            class VARCHAR(10),
            sale_type VARCHAR(50),
            is_multisale BOOLEAN,
            sale_filter_less_than_10k BOOLEAN,
            sale_filter_deed_type BOOLEAN,
            last_synced_at TIMESTAMP WITH TIME ZONE,
            PRIMARY KEY (id)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_parcel_sales_pin_sale_date
        ON parcel_sales_cache (pin, sale_date)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_parcel_sales_sale_date
        ON parcel_sales_cache (sale_date)
    """)

    # 3. improvement_characteristics_cache
    op.execute("""
        CREATE TABLE IF NOT EXISTS improvement_characteristics_cache (
            pin VARCHAR(14) NOT NULL,
            bldg_sf INTEGER,
            beds INTEGER,
            fbath NUMERIC(4, 1),
            hbath NUMERIC(4, 1),
            age INTEGER,
            ext_wall INTEGER,
            apts INTEGER,
            last_synced_at TIMESTAMP WITH TIME ZONE,
            PRIMARY KEY (pin)
        )
    """)

    # 4. sync_log
    op.execute("""
        CREATE TABLE IF NOT EXISTS sync_log (
            id SERIAL NOT NULL,
            dataset_name VARCHAR(100) NOT NULL,
            started_at TIMESTAMP WITH TIME ZONE NOT NULL,
            completed_at TIMESTAMP WITH TIME ZONE,
            rows_upserted INTEGER,
            status VARCHAR(10) NOT NULL,
            error_message TEXT,
            CONSTRAINT ck_sync_log_status CHECK (status IN ('running', 'success', 'failed')),
            PRIMARY KEY (id)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_sync_log_dataset_name
        ON sync_log (dataset_name)
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_sync_log_dataset_name")
    op.execute("DROP TABLE IF EXISTS sync_log")
    op.execute("DROP TABLE IF EXISTS improvement_characteristics_cache")
    op.execute("DROP INDEX IF EXISTS ix_parcel_sales_sale_date")
    op.execute("DROP INDEX IF EXISTS ix_parcel_sales_pin_sale_date")
    op.execute("DROP TABLE IF EXISTS parcel_sales_cache")
    op.execute("DROP INDEX IF EXISTS ix_parcel_universe_lat_lon")
    op.execute("DROP TABLE IF EXISTS parcel_universe_cache")
