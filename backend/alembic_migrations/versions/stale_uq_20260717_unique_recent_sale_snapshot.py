"""Deduplicate recent_sale snapshots, then create the unique index.

Must run after stale_own_20260717 creates the table. Deletes duplicate
non-null sale_date rows before creating uq_lead_owner_snapshots_recent_sale.

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
          AND a.sale_date IS NOT NULL
          AND b.sale_date IS NOT NULL
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


def downgrade():
    op.execute('DROP INDEX IF EXISTS uq_lead_owner_snapshots_recent_sale')
