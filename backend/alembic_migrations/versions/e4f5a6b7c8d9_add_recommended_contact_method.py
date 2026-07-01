"""Add recommended_contact_method column to leads.

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-06-30

Granular outreach scoring ? persist phone / email / text / direct_mail channel.
"""
from alembic import op

revision = 'e4f5a6b7c8d9'
down_revision = 'd3e4f5a6b7c8'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE recommended_contact_method_enum AS ENUM (
                'phone', 'email', 'text', 'direct_mail'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    op.execute("""
        ALTER TABLE leads
        ADD COLUMN IF NOT EXISTS recommended_contact_method recommended_contact_method_enum
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_leads_recommended_contact_method
        ON leads (recommended_contact_method)
    """)


def downgrade():
    op.execute('DROP INDEX IF EXISTS ix_leads_recommended_contact_method')
    op.execute(
        'ALTER TABLE leads DROP COLUMN IF EXISTS recommended_contact_method'
    )
    op.execute('DROP TYPE IF EXISTS recommended_contact_method_enum')
