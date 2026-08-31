"""Channel ROI config + facebook_ad_campaigns

Revision ID: chan_roi_20260831
Revises: joint_own_20260821
Create Date: 2026-08-31
"""
from alembic import op
import sqlalchemy as sa


revision = 'chan_roi_20260831'
down_revision = 'joint_own_20260821'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'channel_roi_config',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('encrypted_meta_token', sa.Text(), nullable=True),
        sa.Column('meta_ad_account_id', sa.String(length=64), nullable=True),
        sa.Column('expected_profit_per_deal', sa.Numeric(12, 2), nullable=True),
        sa.Column('assumed_close_rate', sa.Numeric(5, 4), nullable=True),
        sa.Column('last_synced_at', sa.DateTime(), nullable=True),
        sa.Column('last_sync_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
    )
    op.create_table(
        'facebook_ad_campaigns',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('meta_campaign_id', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=512), nullable=False, server_default=''),
        sa.Column('status', sa.String(length=64), nullable=True),
        sa.Column('spend', sa.Numeric(14, 4), nullable=False, server_default='0'),
        sa.Column('impressions', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('link_clicks', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('response_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('synced_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.UniqueConstraint('meta_campaign_id', name='uq_facebook_ad_campaigns_meta_id'),
    )
    op.create_index(
        'ix_facebook_ad_campaigns_meta_campaign_id',
        'facebook_ad_campaigns',
        ['meta_campaign_id'],
    )


def downgrade():
    op.drop_index('ix_facebook_ad_campaigns_meta_campaign_id', table_name='facebook_ad_campaigns')
    op.drop_table('facebook_ad_campaigns')
    op.drop_table('channel_roi_config')
