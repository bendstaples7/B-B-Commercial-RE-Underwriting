"""Data-only: delete duplicate recent_sale snapshots (non-null sale_date).

Indexes are created in stale_own_20260717; this revision only cleans
duplicate rows so that unique index remains valid.

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


def downgrade():
    pass
