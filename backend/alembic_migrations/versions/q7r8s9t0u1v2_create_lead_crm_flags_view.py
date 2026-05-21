"""Create lead_crm_flags view for computed boolean flags.

Revision ID: q7r8s9t0u1v2
Revises: p6q7r8s9t0u1
Create Date: 2026-05-20 00:04:00.000000

Changes:
  - Create (or replace) view lead_crm_flags with columns:
      lead_id, has_phone_computed, has_email_computed, has_property_match_computed
  - has_phone_computed: TRUE if any phone_1..phone_7 is non-empty OR a ContactPhone exists
  - has_email_computed: TRUE if any email_1..email_5 is non-empty OR a ContactEmail exists
  - has_property_match_computed: TRUE if a confirmed hubspot_match exists

Requirements: Simplification 2 — PostgreSQL view for boolean flags
"""
from alembic import op


revision = 'q7r8s9t0u1v2'
down_revision = 'p6q7r8s9t0u1'
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

            -- has_property_match_computed: a confirmed hubspot_match exists
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


def downgrade():
    op.execute("DROP VIEW IF EXISTS lead_crm_flags")
