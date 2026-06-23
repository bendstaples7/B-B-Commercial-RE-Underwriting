"""Add leads.search_document generated column for ranked fuzzy search.

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-06-22

Adds a stored generated column concatenating owner and address fields,
plus a GIN trigram index for pg_trgm-accelerated fuzzy search.
"""

from alembic import op

revision = 'e7f8a9b0c1d2'
down_revision = 'd6e7f8a9b0c1'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")

    op.execute("""
        ALTER TABLE leads
        ADD COLUMN IF NOT EXISTS search_document text
        GENERATED ALWAYS AS (
            lower(trim(
                coalesce(owner_first_name, '') || ' ' ||
                coalesce(owner_last_name, '') || ' ' ||
                coalesce(owner_2_first_name, '') || ' ' ||
                coalesce(owner_2_last_name, '') || ' ' ||
                coalesce(property_street, '') || ' ' ||
                coalesce(property_city, '') || ' ' ||
                coalesce(property_state, '') || ' ' ||
                coalesce(property_zip, '')
            ))
        ) STORED
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_leads_search_document_trgm
        ON leads USING gin(search_document gin_trgm_ops)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_leads_property_city_trgm
        ON leads USING gin(property_city gin_trgm_ops)
    """)

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_leads_property_zip_trgm
        ON leads USING gin(property_zip gin_trgm_ops)
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_leads_property_zip_trgm")
    op.execute("DROP INDEX IF EXISTS ix_leads_property_city_trgm")
    op.execute("DROP INDEX IF EXISTS ix_leads_search_document_trgm")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS search_document")
