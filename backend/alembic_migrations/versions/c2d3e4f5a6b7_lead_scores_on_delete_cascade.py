"""Add ON DELETE CASCADE to lead_scores.lead_id foreign key.

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-06-29

Score history rows are owned by their lead; deleting a lead should remove
associated lead_scores rows at the database level.
"""
from alembic import op

revision = 'c2d3e4f5a6b7'
down_revision = 'b1c2d3e4f5a6'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE lead_scores DROP CONSTRAINT IF EXISTS lead_scores_lead_id_fkey"
    )
    op.execute(
        """
        ALTER TABLE lead_scores
        ADD CONSTRAINT lead_scores_lead_id_fkey
        FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE
        """
    )


def downgrade():
    op.execute(
        "ALTER TABLE lead_scores DROP CONSTRAINT IF EXISTS lead_scores_lead_id_fkey"
    )
    op.execute(
        """
        ALTER TABLE lead_scores
        ADD CONSTRAINT lead_scores_lead_id_fkey
        FOREIGN KEY (lead_id) REFERENCES leads(id)
        """
    )
