"""Unique recent_sale snapshot per lead+sale; keep lead_sale lookup index.

Revision ID: stale_uq_20260717
Revises: stale_own_20260717
"""

from alembic import op


revision = 'stale_uq_20260717'
down_revision = 'stale_own_20260717'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        DELETE FROM lead_owner_snapshots a
        USING lead_owner_snapshots b
        WHERE a.id > b.id
          AND a.lead_id = b.lead_id
          AND a.sale_date IS NOT DISTINCT FROM b.sale_date
          AND a.reason = 'recent_sale'
          AND b.reason = 'recent_sale'
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_lead_owner_snapshots_recent_sale
        ON lead_owner_snapshots (lead_id, sale_date)
        WHERE reason = 'recent_sale' AND sale_date IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_lead_owner_snapshots_lead_sale
        ON lead_owner_snapshots (lead_id, sale_date)
        """
    )


def downgrade():
    op.execute('DROP INDEX IF EXISTS uq_lead_owner_snapshots_recent_sale')
