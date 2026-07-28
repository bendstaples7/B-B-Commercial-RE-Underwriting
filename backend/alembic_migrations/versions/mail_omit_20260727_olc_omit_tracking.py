"""Add OLC tracked/omitted lead id lists on mail campaigns.

Revision ID: mail_omit_20260727
Revises: mail_rec_20260727
Create Date: 2026-07-27
"""
from alembic import op

revision = 'mail_omit_20260727'
down_revision = 'mail_rec_20260727'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE mail_campaigns
        ADD COLUMN IF NOT EXISTS olc_tracked_lead_ids JSON
    """)
    op.execute("""
        ALTER TABLE mail_campaigns
        ADD COLUMN IF NOT EXISTS olc_omitted_lead_ids JSON
    """)


def downgrade():
    op.execute('ALTER TABLE mail_campaigns DROP COLUMN IF EXISTS olc_omitted_lead_ids')
    op.execute('ALTER TABLE mail_campaigns DROP COLUMN IF EXISTS olc_tracked_lead_ids')
