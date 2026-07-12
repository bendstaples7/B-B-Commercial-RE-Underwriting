"""Add organization entity-lookup fields and organization_parties.

Revision ID: l1m2n3o4p5q6
Revises: k0l1m2n3o4p5
Create Date: 2026-07-12

Supports Illinois LLC entity resolution: store SOS/vendor filing metadata on
organizations and manager/member/officer/RA parties on organization_parties.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'l1m2n3o4p5q6'
down_revision = 'k0l1m2n3o4p5'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    entity_lookup_status = postgresql.ENUM(
        'pending',
        'resolved',
        'no_match',
        'unsupported_jurisdiction',
        'error',
        name='entity_lookup_status_enum',
        create_type=False,
    )
    party_type = postgresql.ENUM(
        'manager',
        'member',
        'officer',
        'registered_agent',
        name='organization_party_type_enum',
        create_type=False,
    )

    # Create enum types idempotently (may already exist from a partial run).
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE entity_lookup_status_enum AS ENUM (
                'pending', 'resolved', 'no_match',
                'unsupported_jurisdiction', 'error'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE organization_party_type_enum AS ENUM (
                'manager', 'member', 'officer', 'registered_agent'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)

    # Add organization columns if missing (partial-run safe).
    op.execute("""
        ALTER TABLE organizations
            ADD COLUMN IF NOT EXISTS jurisdiction VARCHAR(20),
            ADD COLUMN IF NOT EXISTS file_number VARCHAR(50),
            ADD COLUMN IF NOT EXISTS registered_agent_name VARCHAR(500),
            ADD COLUMN IF NOT EXISTS registered_office_address TEXT,
            ADD COLUMN IF NOT EXISTS entity_lookup_status entity_lookup_status_enum,
            ADD COLUMN IF NOT EXISTS entity_lookup_provider VARCHAR(100),
            ADD COLUMN IF NOT EXISTS entity_lookup_checked_at TIMESTAMP WITHOUT TIME ZONE,
            ADD COLUMN IF NOT EXISTS entity_lookup_error TEXT,
            ADD COLUMN IF NOT EXISTS entity_lookup_person_found BOOLEAN NOT NULL DEFAULT FALSE
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_organizations_file_number
        ON organizations (file_number)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_organizations_entity_lookup_status
        ON organizations (entity_lookup_status)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS organization_parties (
            id SERIAL PRIMARY KEY,
            organization_id INTEGER NOT NULL
                REFERENCES organizations(id) ON DELETE CASCADE,
            full_name VARCHAR(500) NOT NULL,
            first_name VARCHAR(128),
            last_name VARCHAR(128),
            party_type organization_party_type_enum NOT NULL,
            is_company BOOLEAN NOT NULL DEFAULT FALSE,
            address TEXT,
            city VARCHAR(100),
            state VARCHAR(50),
            zip VARCHAR(20),
            source VARCHAR(100),
            external_id VARCHAR(100),
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_organization_parties_organization_id
        ON organization_parties (organization_id)
    """)

    # Keep SQLAlchemy metadata references quiet for unused locals.
    _ = (bind, entity_lookup_status, party_type, sa)


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_organization_parties_organization_id")
    op.execute("DROP TABLE IF EXISTS organization_parties")
    op.execute("DROP INDEX IF EXISTS ix_organizations_entity_lookup_status")
    op.execute("DROP INDEX IF EXISTS ix_organizations_file_number")
    op.execute("""
        ALTER TABLE organizations
            DROP COLUMN IF EXISTS entity_lookup_person_found,
            DROP COLUMN IF EXISTS entity_lookup_error,
            DROP COLUMN IF EXISTS entity_lookup_checked_at,
            DROP COLUMN IF EXISTS entity_lookup_provider,
            DROP COLUMN IF EXISTS entity_lookup_status,
            DROP COLUMN IF EXISTS registered_office_address,
            DROP COLUMN IF EXISTS registered_agent_name,
            DROP COLUMN IF EXISTS file_number,
            DROP COLUMN IF EXISTS jurisdiction
    """)
    op.execute("DROP TYPE IF EXISTS organization_party_type_enum")
    op.execute("DROP TYPE IF EXISTS entity_lookup_status_enum")
