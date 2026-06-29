"""Add violation_data, permit_data columns to leads and data_enrichment_weight to scoring_weights

Revision ID: 97321ab5e710
Revises: h2i3j4k5l6m7
Create Date: 2026-06-26 11:53:41.549700

Adds columns required for the Data Enrichment Scoring feature:
- leads.violation_data (JSONB, nullable) — stores code violation records
- leads.permit_data (JSONB, nullable) — stores building permit records
- leads.most_recent_sale_price (FLOAT, nullable) — most recent sale price for equity scoring
- scoring_weights.data_enrichment_weight (FLOAT, NOT NULL, default 0.20)
  — configurable weight for data enrichment in lead scoring

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '97321ab5e710'
down_revision = 'h2i3j4k5l6m7'
branch_labels = None
depends_on = None


def upgrade():
    # Add violation_data (JSONB, nullable) to leads
    op.execute(
        'ALTER TABLE leads ADD COLUMN IF NOT EXISTS violation_data JSONB'
    )
    # Add permit_data (JSONB, nullable) to leads
    op.execute(
        'ALTER TABLE leads ADD COLUMN IF NOT EXISTS permit_data JSONB'
    )
    # Add most_recent_sale_price (FLOAT, nullable) to leads
    op.execute(
        'ALTER TABLE leads ADD COLUMN IF NOT EXISTS most_recent_sale_price DOUBLE PRECISION'
    )
    # Add data_enrichment_weight (FLOAT, NOT NULL, default 0.20) to scoring_weights
    op.execute(
        'ALTER TABLE scoring_weights '
        'ADD COLUMN IF NOT EXISTS data_enrichment_weight DOUBLE PRECISION '
        'NOT NULL DEFAULT 0.20'
    )
    # Rebalance existing rows so the five weights sum to 1.0 (scale core weights to 0.80).
    op.execute(
        'UPDATE scoring_weights SET '
        'property_characteristics_weight = property_characteristics_weight * 0.80, '
        'data_completeness_weight = data_completeness_weight * 0.80, '
        'owner_situation_weight = owner_situation_weight * 0.80, '
        'location_desirability_weight = location_desirability_weight * 0.80 '
        'WHERE data_enrichment_weight = 0.20'
    )
    # Extend parcel_universe_cache with assessor fields used by enrichment scoring
    op.execute(
        'ALTER TABLE parcel_universe_cache ADD COLUMN IF NOT EXISTS property_class VARCHAR(10)'
    )
    op.execute(
        'ALTER TABLE parcel_universe_cache '
        'ADD COLUMN IF NOT EXISTS lot_size INTEGER'
    )
    op.execute(
        'ALTER TABLE parcel_universe_cache '
        'ADD COLUMN IF NOT EXISTS assessed_value DOUBLE PRECISION'
    )


def downgrade():
    op.execute(
        'ALTER TABLE scoring_weights DROP COLUMN IF EXISTS data_enrichment_weight'
    )
    op.execute(
        'ALTER TABLE leads DROP COLUMN IF EXISTS permit_data'
    )
    op.execute(
        'ALTER TABLE leads DROP COLUMN IF EXISTS violation_data'
    )
    op.execute(
        'ALTER TABLE leads DROP COLUMN IF EXISTS most_recent_sale_price'
    )
    op.execute(
        'ALTER TABLE parcel_universe_cache DROP COLUMN IF EXISTS assessed_value'
    )
    op.execute(
        'ALTER TABLE parcel_universe_cache DROP COLUMN IF EXISTS lot_size'
    )
    op.execute(
        'ALTER TABLE parcel_universe_cache DROP COLUMN IF EXISTS property_class'
    )