"""Update lead_crm_flags view: include GIS has_property_match in computed flag.

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-06-17

Problem:
    has_property_match_computed in lead_crm_flags was defined as TRUE only
    when a confirmed hubspot_match exists.  This meant that leads imported
    via Google Sheets or other non-HubSpot paths — even after GIS enrichment
    successfully set leads.has_property_match = TRUE and populated the PIN —
    were still treated as unmatched by ActionEngineService, causing the
    "Resolve Property Match" recommended action to remain stuck.

Fix:
    has_property_match_computed = TRUE when EITHER:
      - A confirmed hubspot_match exists (original condition), OR
      - leads.has_property_match = TRUE (set by GIS enrichment or manually)

This is idempotent — CREATE OR REPLACE VIEW replaces the existing view.
"""
from alembic import op

revision = 'c5d6e7f8a9b0'
down_revision = 'b4c5d6e7f8a9'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE OR REPLACE VIEW lead_crm_flags AS
        SELECT
            l.id AS lead_id,

            -- has_phone_computed: any non-empty phone column OR a ContactPhone record exists
            (
                COALESCE(NULLIF(TRIM(l.phone_1), ''), NULL) IS NOT NULL
                OR COALESCE(NULLIF(TRIM(l.phone_2), ''), NULL) IS NOT NULL
                OR COALESCE(NULLIF(TRIM(l.phone_3), ''), NULL) IS NOT NULL
                OR COALESCE(NULLIF(TRIM(l.phone_4), ''), NULL) IS NOT NULL
                OR COALESCE(NULLIF(TRIM(l.phone_5), ''), NULL) IS NOT NULL
                OR COALESCE(NULLIF(TRIM(l.phone_6), ''), NULL) IS NOT NULL
                OR COALESCE(NULLIF(TRIM(l.phone_7), ''), NULL) IS NOT NULL
                OR EXISTS (
                    SELECT 1
                    FROM contact_phones cp
                    JOIN property_contacts pc ON pc.contact_id = cp.contact_id
                    WHERE pc.property_id = l.id
                )
            ) AS has_phone_computed,

            -- has_email_computed: any non-empty email column OR a ContactEmail record exists
            (
                COALESCE(NULLIF(TRIM(l.email_1), ''), NULL) IS NOT NULL
                OR COALESCE(NULLIF(TRIM(l.email_2), ''), NULL) IS NOT NULL
                OR COALESCE(NULLIF(TRIM(l.email_3), ''), NULL) IS NOT NULL
                OR COALESCE(NULLIF(TRIM(l.email_4), ''), NULL) IS NOT NULL
                OR COALESCE(NULLIF(TRIM(l.email_5), ''), NULL) IS NOT NULL
                OR EXISTS (
                    SELECT 1
                    FROM contact_emails ce
                    JOIN property_contacts pc ON pc.contact_id = ce.contact_id
                    WHERE pc.property_id = l.id
                )
            ) AS has_email_computed,

            -- has_property_match_computed: confirmed hubspot_match OR GIS match
            -- (leads.has_property_match set by GIS enrichment / backfill)
            (
                l.has_property_match = TRUE
                OR EXISTS (
                    SELECT 1
                    FROM hubspot_matches hm
                    WHERE hm.internal_record_id = l.id
                      AND hm.internal_record_type = 'lead'
                      AND hm.status = 'confirmed'
                )
            ) AS has_property_match_computed

        FROM leads l
    """)


def downgrade():
    # Restore the original view definition (HubSpot-only match condition)
    op.execute("""
        CREATE OR REPLACE VIEW lead_crm_flags AS
        SELECT
            l.id AS lead_id,

            (
                COALESCE(NULLIF(TRIM(l.phone_1), ''), NULL) IS NOT NULL
                OR COALESCE(NULLIF(TRIM(l.phone_2), ''), NULL) IS NOT NULL
                OR COALESCE(NULLIF(TRIM(l.phone_3), ''), NULL) IS NOT NULL
                OR COALESCE(NULLIF(TRIM(l.phone_4), ''), NULL) IS NOT NULL
                OR COALESCE(NULLIF(TRIM(l.phone_5), ''), NULL) IS NOT NULL
                OR COALESCE(NULLIF(TRIM(l.phone_6), ''), NULL) IS NOT NULL
                OR COALESCE(NULLIF(TRIM(l.phone_7), ''), NULL) IS NOT NULL
                OR EXISTS (
                    SELECT 1
                    FROM contact_phones cp
                    JOIN property_contacts pc ON pc.contact_id = cp.contact_id
                    WHERE pc.property_id = l.id
                )
            ) AS has_phone_computed,

            (
                COALESCE(NULLIF(TRIM(l.email_1), ''), NULL) IS NOT NULL
                OR COALESCE(NULLIF(TRIM(l.email_2), ''), NULL) IS NOT NULL
                OR COALESCE(NULLIF(TRIM(l.email_3), ''), NULL) IS NOT NULL
                OR COALESCE(NULLIF(TRIM(l.email_4), ''), NULL) IS NOT NULL
                OR COALESCE(NULLIF(TRIM(l.email_5), ''), NULL) IS NOT NULL
                OR EXISTS (
                    SELECT 1
                    FROM contact_emails ce
                    JOIN property_contacts pc ON pc.contact_id = ce.contact_id
                    WHERE pc.property_id = l.id
                )
            ) AS has_email_computed,

            (
                EXISTS (
                    SELECT 1
                    FROM hubspot_matches hm
                    WHERE hm.internal_record_id = l.id
                      AND hm.internal_record_type = 'lead'
                      AND hm.status = 'confirmed'
                )
            ) AS has_property_match_computed

        FROM leads l
    """)
