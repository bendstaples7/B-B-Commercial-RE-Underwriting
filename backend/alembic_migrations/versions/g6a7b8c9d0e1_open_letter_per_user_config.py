"""Per-user Open Letter Connect config — add user_id column.

Revision ID: g6a7b8c9d0e1
Revises: f5a6b7c8d9e0
Create Date: 2026-07-01
"""
from alembic import op

revision = 'g6a7b8c9d0e1'
down_revision = 'f5a6b7c8d9e0'
branch_labels = None
depends_on = None

BEN_USER_ID = 'e5bc61c7-4db1-4307-a7b6-0a6b5a3d84c9'


def upgrade():
    op.execute(
        "ALTER TABLE open_letter_config ADD COLUMN IF NOT EXISTS user_id VARCHAR(36)"
    )
    op.execute(f"""
        UPDATE open_letter_config
        SET user_id = '{BEN_USER_ID}'
        WHERE user_id IS NULL
    """)
    op.execute("""
        ALTER TABLE open_letter_config
        ALTER COLUMN user_id SET NOT NULL
    """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_open_letter_config_user_id
        ON open_letter_config (user_id)
    """)
    op.execute('DROP INDEX IF EXISTS uq_mail_queue_lead_queued')
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_mail_queue_user_lead_queued
        ON mail_queue_items (user_id, lead_id)
        WHERE status = 'queued'
    """)


def downgrade():
    op.execute('DROP INDEX IF EXISTS uq_mail_queue_user_lead_queued')
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_mail_queue_lead_queued
        ON mail_queue_items (lead_id)
        WHERE status = 'queued'
    """)
    op.execute('DROP INDEX IF EXISTS uq_open_letter_config_user_id')
    op.execute('ALTER TABLE open_letter_config DROP COLUMN IF EXISTS user_id')
