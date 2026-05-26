"""add_is_admin_to_users

Revision ID: t0u1v2w3x4y5
Revises: r8s9t0u1v2w3
Create Date: 2025-01-01 00:00:00.000000

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = 't0u1v2w3x4y5'
down_revision = 'r8s9t0u1v2w3'
branch_labels = None
depends_on = None


def upgrade():
    # Add is_admin column (idempotent — safe to run more than once)
    op.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE
    """)

    # Grant admin privileges to the designated admin user if they exist.
    # Skips silently if the user doesn't exist yet (e.g. on a fresh local DB).
    import os
    admin_email = os.environ.get('ADMIN_EMAIL', '').lower().strip()
    if admin_email:
        op.get_bind().execute(
            __import__('sqlalchemy').text(
                "UPDATE users SET is_admin = TRUE WHERE email_lower = :email"
            ),
            {'email': admin_email}
        )


def downgrade():
    op.execute("""
        ALTER TABLE users
        DROP COLUMN IF EXISTS is_admin
    """)
