"""Add ready-to-mail queue filter and sort index.

Revision ID: rtm_idx_20260721
Revises: addr_tl_20260719
"""

from alembic import op


revision = 'rtm_idx_20260721'
down_revision = 'addr_tl_20260719'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_leads_mail_queue_filter_score
        ON leads (owner_user_id, recommended_action, lead_status, lead_score DESC)
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_leads_mail_queue_filter_score")
