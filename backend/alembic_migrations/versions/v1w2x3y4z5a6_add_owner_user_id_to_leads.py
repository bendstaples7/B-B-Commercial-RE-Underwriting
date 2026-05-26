"""add owner_user_id to leads

Revision ID: v1w2x3y4z5a6
Revises: u1v2w3x4y5z6
Create Date: 2026-05-25

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'v1w2x3y4z5a6'
down_revision = 'u1v2w3x4y5z6'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE leads
        ADD COLUMN IF NOT EXISTS owner_user_id VARCHAR(36)
            REFERENCES users(user_id) ON DELETE SET NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_leads_owner_user_id ON leads(owner_user_id)
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_leads_owner_user_id")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS owner_user_id")
