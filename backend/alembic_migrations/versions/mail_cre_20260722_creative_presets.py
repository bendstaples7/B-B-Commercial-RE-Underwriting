"""Add creative presets on Open Letter config and creative snapshot on campaigns.

Revision ID: mail_cre_20260722
Revises: lead_stg_20260722
"""
from alembic import op
import sqlalchemy as sa

revision = 'mail_cre_20260722'
down_revision = 'lead_stg_20260722'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'open_letter_config',
        sa.Column('creative_presets', sa.JSON(), nullable=True),
    )
    op.add_column(
        'open_letter_config',
        sa.Column('active_creative_preset_id', sa.String(length=64), nullable=True),
    )
    op.add_column(
        'mail_campaigns',
        sa.Column('creative', sa.JSON(), nullable=True),
    )


def downgrade():
    op.drop_column('mail_campaigns', 'creative')
    op.drop_column('open_letter_config', 'active_creative_preset_id')
    op.drop_column('open_letter_config', 'creative_presets')
