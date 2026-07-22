"""Add creative presets on Open Letter config and creative snapshot on campaigns.

Revision ID: mail_cre_20260722
Revises: lead_stg_20260722
"""
from alembic import op

revision = 'mail_cre_20260722'
down_revision = 'lead_stg_20260722'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE open_letter_config
        ADD COLUMN IF NOT EXISTS creative_presets JSONB
    """)
    op.execute("""
        ALTER TABLE open_letter_config
        ADD COLUMN IF NOT EXISTS active_creative_preset_id VARCHAR(64)
    """)
    op.execute("""
        ALTER TABLE mail_campaigns
        ADD COLUMN IF NOT EXISTS creative JSONB
    """)


def downgrade():
    op.execute("ALTER TABLE mail_campaigns DROP COLUMN IF EXISTS creative")
    op.execute(
        "ALTER TABLE open_letter_config "
        "DROP COLUMN IF EXISTS active_creative_preset_id"
    )
    op.execute(
        "ALTER TABLE open_letter_config DROP COLUMN IF EXISTS creative_presets"
    )
