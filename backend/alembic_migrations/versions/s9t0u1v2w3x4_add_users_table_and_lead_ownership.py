"""Add users table and lead ownership (owner_user_id).

Revision ID: s9t0u1v2w3x4
Revises: r8s9t0u1v2w3
Create Date: 2026-05-21 00:00:00.000000

Changes:
  - Create table users with all required columns and indexes
  - Seed Ben's account (ben.d.staples.7@gmail.com) with bcrypt-hashed password
  - Add owner_user_id VARCHAR(36) column to leads
  - Assign all NULL-owner leads to Ben
  - Add NOT NULL constraint to leads.owner_user_id
  - Add FK constraint fk_leads_owner on leads.owner_user_id -> users.user_id
  - Conditionally seed User_X if USER_X_EMAIL and USER_X_NAME env vars are set
"""
import logging
import os
import secrets
import string
import uuid

import bcrypt
from alembic import op

revision = 's9t0u1v2w3x4'
down_revision = 'r8s9t0u1v2w3'
branch_labels = None
depends_on = None

logger = logging.getLogger('alembic.runtime.migration')


def _generate_password(length: int = 20) -> str:
    """Generate a cryptographically secure random password."""
    alphabet = string.ascii_letters + string.digits + string.punctuation
    # Ensure at least one of each character class
    password = [
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.digits),
        secrets.choice(string.punctuation),
    ]
    password += [secrets.choice(alphabet) for _ in range(length - 4)]
    secrets.SystemRandom().shuffle(password)
    return ''.join(password)


def _hash_password(plaintext: str) -> str:
    """Hash a plaintext password with bcrypt work factor 12."""
    return bcrypt.hashpw(plaintext.encode('utf-8'), bcrypt.gensalt(rounds=12)).decode('utf-8')


def upgrade():
    # ------------------------------------------------------------------
    # Step 1: Create the users table (idempotent)
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            SERIAL PRIMARY KEY,
            user_id       VARCHAR(36)  NOT NULL,
            email         VARCHAR(254) NOT NULL,
            email_lower   VARCHAR(254) NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            display_name  VARCHAR(100) NOT NULL,
            is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
            created_at    TIMESTAMP    NOT NULL DEFAULT NOW(),
            updated_at    TIMESTAMP    NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_users_user_id    UNIQUE (user_id),
            CONSTRAINT uq_users_email_lower UNIQUE (email_lower)
        )
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_users_user_id
        ON users(user_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_users_email_lower
        ON users(email_lower)
    """)

    # ------------------------------------------------------------------
    # Step 2: Seed Ben's account
    # ------------------------------------------------------------------
    ben_email = 'ben.d.staples.7@gmail.com'
    ben_email_lower = ben_email.lower()
    ben_display_name = 'Ben'
    ben_user_id = str(uuid.uuid4())

    ben_password = os.environ.get('BEN_INITIAL_PASSWORD')
    if not ben_password:
        ben_password = _generate_password()
        print(
            f'\n[MIGRATION s9t0u1v2w3x4] BEN_INITIAL_PASSWORD env var not set. '
            f'Generated random password for {ben_email}: {ben_password}\n'
            f'RECORD THIS PASSWORD — it will not be shown again.\n'
        )

    ben_password_hash = _hash_password(ben_password)

    op.execute(f"""
        INSERT INTO users (user_id, email, email_lower, password_hash, display_name, is_active, created_at, updated_at)
        VALUES (
            '{ben_user_id}',
            '{ben_email}',
            '{ben_email_lower}',
            '{ben_password_hash}',
            '{ben_display_name}',
            TRUE,
            NOW(),
            NOW()
        )
        ON CONFLICT (email_lower) DO NOTHING
    """)

    # ------------------------------------------------------------------
    # Step 3: Add owner_user_id column to leads (idempotent)
    # ------------------------------------------------------------------
    op.execute("""
        ALTER TABLE leads
        ADD COLUMN IF NOT EXISTS owner_user_id VARCHAR(36)
    """)

    # ------------------------------------------------------------------
    # Step 4: Assign all NULL-owner leads to Ben
    # ------------------------------------------------------------------
    op.execute(f"""
        UPDATE leads
        SET owner_user_id = (
            SELECT user_id FROM users WHERE email_lower = '{ben_email_lower}'
        )
        WHERE owner_user_id IS NULL
    """)

    # ------------------------------------------------------------------
    # Step 5: Add NOT NULL constraint to owner_user_id
    # ------------------------------------------------------------------
    op.execute("""
        ALTER TABLE leads
        ALTER COLUMN owner_user_id SET NOT NULL
    """)

    # ------------------------------------------------------------------
    # Step 6: Add FK constraint (idempotent via DO $$ BEGIN ... END $$)
    # PostgreSQL does not support ADD CONSTRAINT IF NOT EXISTS directly,
    # so we use the duplicate_object exception pattern.
    # ------------------------------------------------------------------
    op.execute("""
        DO $$ BEGIN
            ALTER TABLE leads
            ADD CONSTRAINT fk_leads_owner
            FOREIGN KEY (owner_user_id) REFERENCES users(user_id);
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)

    # ------------------------------------------------------------------
    # Step 7: Conditionally seed User_X
    # ------------------------------------------------------------------
    user_x_email = os.environ.get('USER_X_EMAIL')
    user_x_name = os.environ.get('USER_X_NAME')

    if user_x_email and user_x_name:
        user_x_email_lower = user_x_email.lower()
        user_x_user_id = str(uuid.uuid4())
        user_x_password = _generate_password()
        user_x_password_hash = _hash_password(user_x_password)

        # Escape single quotes in name/email for SQL safety
        safe_email = user_x_email.replace("'", "''")
        safe_email_lower = user_x_email_lower.replace("'", "''")
        safe_name = user_x_name.replace("'", "''")

        print(
            f'\n[MIGRATION s9t0u1v2w3x4] Seeding User_X account for {user_x_email}. '
            f'Generated password: {user_x_password}\n'
            f'RECORD THIS PASSWORD — it will not be shown again.\n'
        )

        op.execute(f"""
            INSERT INTO users (user_id, email, email_lower, password_hash, display_name, is_active, created_at, updated_at)
            VALUES (
                '{user_x_user_id}',
                '{safe_email}',
                '{safe_email_lower}',
                '{user_x_password_hash}',
                '{safe_name}',
                TRUE,
                NOW(),
                NOW()
            )
            ON CONFLICT (email_lower) DO NOTHING
        """)
    else:
        missing = []
        if not user_x_email:
            missing.append('USER_X_EMAIL')
        if not user_x_name:
            missing.append('USER_X_NAME')
        logger.warning(
            '[MIGRATION s9t0u1v2w3x4] Skipping User_X seeding — '
            'missing env var(s): %s. Set these and re-run to provision User_X.',
            ', '.join(missing)
        )


def downgrade():
    # Drop FK constraint
    op.execute("""
        ALTER TABLE leads
        DROP CONSTRAINT IF EXISTS fk_leads_owner
    """)

    # Drop owner_user_id column (also removes NOT NULL constraint)
    op.execute("""
        ALTER TABLE leads
        DROP COLUMN IF EXISTS owner_user_id
    """)

    # Drop users table (and its indexes, which are dropped automatically)
    op.execute("DROP TABLE IF EXISTS users")
