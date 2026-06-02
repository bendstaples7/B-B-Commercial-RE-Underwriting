"""seed sub users and reassign leads

Revision ID: w2x3y4z5a6b7
Revises: v1w2x3y4z5a6
Create Date: 2026-05-25

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'w2x3y4z5a6b7'
down_revision = 'v1w2x3y4z5a6'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Add password_set column if it doesn't exist
    op.execute("""
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS password_set BOOLEAN NOT NULL DEFAULT FALSE
    """)

    # 2. Mark existing users (who already have a password hash) as password_set = true
    op.execute("""
        UPDATE users
        SET password_set = TRUE
        WHERE password_hash IS NOT NULL AND password_hash != ''
    """)

    # 3. Insert ben.d.staples.7@gmail.com (sub-user, no password set yet)
    op.execute("""
        INSERT INTO users (
            user_id, email, email_lower, display_name,
            password_hash, is_active, is_admin, password_set,
            created_at, updated_at
        )
        VALUES (
            gen_random_uuid()::text,
            'ben.d.staples.7@gmail.com',
            'ben.d.staples.7@gmail.com',
            'Ben',
            '',
            true,
            false,
            false,
            NOW(),
            NOW()
        )
        ON CONFLICT (email_lower) DO NOTHING
    """)

    # 4. Insert userx@test.com (sub-user, no password set yet)
    op.execute("""
        INSERT INTO users (
            user_id, email, email_lower, display_name,
            password_hash, is_active, is_admin, password_set,
            created_at, updated_at
        )
        VALUES (
            gen_random_uuid()::text,
            'userx@test.com',
            'userx@test.com',
            'UserX',
            '',
            true,
            false,
            false,
            NOW(),
            NOW()
        )
        ON CONFLICT (email_lower) DO NOTHING
    """)

    # 5. Reassign unowned leads to ben.d.staples.7@gmail.com
    op.execute("""
        UPDATE leads
        SET owner_user_id = (
            SELECT user_id FROM users WHERE email_lower = 'ben.d.staples.7@gmail.com'
        )
        WHERE owner_user_id IS NULL
    """)


def downgrade():
    # Only drop the password_set column — do NOT undo user inserts or lead reassignment
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS password_set")
