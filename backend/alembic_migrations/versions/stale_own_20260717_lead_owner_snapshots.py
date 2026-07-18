"""Add former_owner role, superseded_at, and lead_owner_snapshots.

Unique recent_sale index is created in stale_uq_20260717 after duplicate cleanup.

Revision ID: stale_own_20260717
Revises: act_goals_fk_20260716
"""

from alembic import op


revision = 'stale_own_20260717'
down_revision = 'act_goals_fk_20260716'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TYPE property_contact_role_enum "
        "ADD VALUE IF NOT EXISTS 'former_owner'"
    )
    op.execute(
        """
        ALTER TABLE property_contacts
        ADD COLUMN IF NOT EXISTS superseded_at TIMESTAMP WITH TIME ZONE
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS lead_owner_snapshots (
            id SERIAL PRIMARY KEY,
            lead_id INTEGER NOT NULL
                REFERENCES leads(id) ON DELETE CASCADE,
            captured_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            reason VARCHAR(40) NOT NULL,
            sale_date DATE,
            payload JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_lead_owner_snapshots_lead_id
        ON lead_owner_snapshots (lead_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_lead_owner_snapshots_lead_sale
        ON lead_owner_snapshots (lead_id, sale_date)
        """
    )


def downgrade():
    op.execute('DROP INDEX IF EXISTS ix_lead_owner_snapshots_lead_sale')
    op.execute('DROP INDEX IF EXISTS ix_lead_owner_snapshots_lead_id')
    op.execute('DROP TABLE IF EXISTS lead_owner_snapshots')
    op.execute(
        'ALTER TABLE property_contacts DROP COLUMN IF EXISTS superseded_at'
    )
    # Postgres cannot easily remove enum values; leave former_owner in place.
