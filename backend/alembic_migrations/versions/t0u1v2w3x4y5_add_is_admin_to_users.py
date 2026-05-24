"""add_is_admin_to_users

Revision ID: t0u1v2w3x4y5
Revises: s9t0u1v2w3x4
Create Date: 2025-01-01 00:00:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 't0u1v2w3x4y5'
down_revision = 's9t0u1v2w3x4'
branch_labels = None
depends_on = None


def upgrade():
    # Add is_admin column (idempotent — safe to run more than once)
    op.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE
    """)

    # Grant admin privileges to the designated admin user
    op.execute("""
        UPDATE users
        SET is_admin = TRUE
        WHERE email_lower = 'ben.d.staples.7@gmail.com'
    """)


def downgrade():
    op.execute("""
        ALTER TABLE users
        DROP COLUMN IF EXISTS is_admin
    """)
