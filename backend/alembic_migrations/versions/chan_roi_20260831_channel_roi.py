"""Channel ROI config + facebook_ad_campaigns

Revision ID: chan_roi_20260831
Revises: joint_own_20260821
Create Date: 2026-08-31
"""
from alembic import op


revision = 'chan_roi_20260831'
down_revision = 'joint_own_20260821'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS channel_roi_config (
            id SERIAL PRIMARY KEY,
            encrypted_meta_token TEXT,
            meta_ad_account_id VARCHAR(64),
            expected_profit_per_deal NUMERIC(12, 2),
            assumed_close_rate NUMERIC(5, 4),
            last_synced_at TIMESTAMP WITHOUT TIME ZONE,
            last_sync_error TEXT,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS facebook_ad_campaigns (
            id SERIAL PRIMARY KEY,
            meta_campaign_id VARCHAR(64) NOT NULL,
            name VARCHAR(512) NOT NULL DEFAULT '',
            status VARCHAR(64),
            spend NUMERIC(14, 4) NOT NULL DEFAULT 0,
            impressions INTEGER NOT NULL DEFAULT 0,
            link_clicks INTEGER NOT NULL DEFAULT 0,
            response_count INTEGER NOT NULL DEFAULT 0,
            synced_at TIMESTAMP WITHOUT TIME ZONE,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_facebook_ad_campaigns_meta_id UNIQUE (meta_campaign_id)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_facebook_ad_campaigns_meta_campaign_id
        ON facebook_ad_campaigns (meta_campaign_id)
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_facebook_ad_campaigns_meta_campaign_id")
    op.execute("DROP TABLE IF EXISTS facebook_ad_campaigns")
    op.execute("DROP TABLE IF EXISTS channel_roi_config")
