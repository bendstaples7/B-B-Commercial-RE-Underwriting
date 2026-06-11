"""Add pg_trgm extension and trigram indexes for global search.

Revision ID: a3b4c5d6e7f8
Revises: z1b2c3d4e5f6
Create Date: 2026-06-11 00:00:00.000000

Changes:
  - Enable pg_trgm PostgreSQL extension (idempotent, IF NOT EXISTS)
  - Add GIN trigram index on leads.owner_first_name
  - Add GIN trigram index on leads.owner_last_name
  - Add GIN trigram index on leads.property_street
  - Add GIN trigram index on property_facts.address

These indexes accelerate ILIKE '%q%' queries used by the global search bar
(GET /api/search) from O(n) full-table scans to sub-linear GIN lookups.
The controller falls back gracefully to plain ILIKE when pg_trgm is not
available (e.g. SQLite in tests), so the migration is safe to skip in
test environments.

Requirements: 9.7 (pg_trgm), 9.8 (LIMIT), 9.9 (response time)
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = 'a3b4c5d6e7f8'
down_revision = 'z1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    # Enable the pg_trgm extension for trigram similarity support.
    # IF NOT EXISTS makes this safe to run on databases that already have it.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")

    # GIN trigram index on leads.owner_first_name
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_leads_owner_first_name_trgm
        ON leads USING gin(owner_first_name gin_trgm_ops)
    """)

    # GIN trigram index on leads.owner_last_name
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_leads_owner_last_name_trgm
        ON leads USING gin(owner_last_name gin_trgm_ops)
    """)

    # GIN trigram index on leads.property_street
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_leads_property_street_trgm
        ON leads USING gin(property_street gin_trgm_ops)
    """)

    # GIN trigram index on property_facts.address
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_property_facts_address_trgm
        ON property_facts USING gin(address gin_trgm_ops)
    """)


def downgrade():
    # Drop indexes in reverse order; IF EXISTS makes each statement idempotent.
    # Note: we do NOT drop the pg_trgm extension — other indexes or queries
    # in the database may depend on it.
    op.execute("DROP INDEX IF EXISTS ix_property_facts_address_trgm")
    op.execute("DROP INDEX IF EXISTS ix_leads_property_street_trgm")
    op.execute("DROP INDEX IF EXISTS ix_leads_owner_last_name_trgm")
    op.execute("DROP INDEX IF EXISTS ix_leads_owner_first_name_trgm")
