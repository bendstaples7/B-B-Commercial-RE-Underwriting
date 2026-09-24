"""Add lead_tasks.notes, leads.lead_subtype, and lead_units inventory.

Revision ID: lead_cap_20260924
Revises: deal_src_20260924
Create Date: 2026-09-24

Supports address-optional capture, per-unit mix/rent, subtype (mixed_use),
and conversation notes on open tasks.
"""
from alembic import op

revision = 'lead_cap_20260924'
down_revision = 'deal_src_20260924'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE lead_tasks ADD COLUMN IF NOT EXISTS notes TEXT"
    )
    op.execute(
        """
        ALTER TABLE leads
        ADD COLUMN IF NOT EXISTS lead_subtype VARCHAR(50)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS lead_units (
            id SERIAL PRIMARY KEY,
            lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
            unit_label VARCHAR(50) NOT NULL,
            unit_type VARCHAR(50) NOT NULL DEFAULT 'residential',
            beds INTEGER,
            baths NUMERIC(4, 1),
            sqft INTEGER,
            current_rent NUMERIC(12, 2),
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_lead_units_lead_label UNIQUE (lead_id, unit_label)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_lead_units_lead_id ON lead_units (lead_id)"
    )


def downgrade():
    op.execute('DROP INDEX IF EXISTS ix_lead_units_lead_id')
    op.execute('DROP TABLE IF EXISTS lead_units')
    op.execute('ALTER TABLE leads DROP COLUMN IF EXISTS lead_subtype')
    op.execute('ALTER TABLE lead_tasks DROP COLUMN IF EXISTS notes')
