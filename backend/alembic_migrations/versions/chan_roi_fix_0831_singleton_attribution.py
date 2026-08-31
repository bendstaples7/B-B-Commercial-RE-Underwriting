"""Channel ROI singleton key + Facebook attribution ledger

Revision ID: chan_roi_fix_0831
Revises: chan_roi_20260831
Create Date: 2026-08-31
"""
from alembic import op


revision = 'chan_roi_fix_0831'
down_revision = 'chan_roi_20260831'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE channel_roi_config
        ADD COLUMN IF NOT EXISTS config_key VARCHAR(32) NOT NULL DEFAULT 'default'
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_channel_roi_config_key
        ON channel_roi_config (config_key)
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS facebook_campaign_lead_attributions (
            lead_id INTEGER NOT NULL REFERENCES leads(id),
            facebook_campaign_id INTEGER NOT NULL REFERENCES facebook_ad_campaigns(id),
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            PRIMARY KEY (lead_id, facebook_campaign_id)
        )
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS facebook_campaign_lead_attributions")
    op.execute("DROP INDEX IF EXISTS uq_channel_roi_config_key")
    op.execute("""
        ALTER TABLE channel_roi_config
        DROP COLUMN IF EXISTS config_key
    """)
