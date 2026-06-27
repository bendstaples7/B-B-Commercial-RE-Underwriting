"""Add confidence tracking columns to contact_phones.

Revision ID: j4k5l6m7n8o9
Revises: i3j4k5l6m7n8
Create Date: 2026-06-26
"""
from alembic import op

revision = 'j4k5l6m7n8o9'
down_revision = 'i3j4k5l6m7n8'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE contact_phone_source_enum AS ENUM (
                'manual', 'hubspot_import', 'flat_backfill'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        ALTER TABLE contact_phones
        ADD COLUMN IF NOT EXISTS notes TEXT
    """)
    op.execute("""
        ALTER TABLE contact_phones
        ADD COLUMN IF NOT EXISTS confidence_score SMALLINT
    """)
    op.execute("""
        ALTER TABLE contact_phones
        ADD COLUMN IF NOT EXISTS last_outcome VARCHAR(30)
    """)
    op.execute("""
        ALTER TABLE contact_phones
        ADD COLUMN IF NOT EXISTS last_called_at TIMESTAMP
    """)
    op.execute("""
        ALTER TABLE contact_phones
        ADD COLUMN IF NOT EXISTS source contact_phone_source_enum
    """)


def downgrade():
    op.execute("ALTER TABLE contact_phones DROP COLUMN IF EXISTS source")
    op.execute("ALTER TABLE contact_phones DROP COLUMN IF EXISTS last_called_at")
    op.execute("ALTER TABLE contact_phones DROP COLUMN IF EXISTS last_outcome")
    op.execute("ALTER TABLE contact_phones DROP COLUMN IF EXISTS confidence_score")
    op.execute("ALTER TABLE contact_phones DROP COLUMN IF EXISTS notes")
    op.execute("DROP TYPE IF EXISTS contact_phone_source_enum")
