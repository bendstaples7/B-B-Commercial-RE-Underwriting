"""Add assessed_value column to leads table.

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-06-29

The Lead ORM model expects leads.assessed_value for enrichment scoring;
97321ab5e710 added assessed_value to parcel_universe_cache only.
"""
from alembic import op

revision = 'd3e4f5a6b7c8'
down_revision = 'c2d3e4f5a6b7'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        'ALTER TABLE leads ADD COLUMN IF NOT EXISTS assessed_value DOUBLE PRECISION'
    )


def downgrade():
    op.execute(
        'ALTER TABLE leads DROP COLUMN IF EXISTS assessed_value'
    )
