"""Ensure Facebook attribution ledger FKs cascade on lead/campaign delete

Revision ID: chan_roi_cascade_0831
Revises: chan_roi_fix_0831
Create Date: 2026-08-31
"""
from alembic import op


revision = 'chan_roi_cascade_0831'
down_revision = 'chan_roi_fix_0831'
branch_labels = None
depends_on = None


def upgrade():
    # Idempotent repair for DBs that already created the ledger without ON DELETE CASCADE.
    op.execute("""
        DO $$
        DECLARE
            r RECORD;
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_name = 'facebook_campaign_lead_attributions'
            ) THEN
                RETURN;
            END IF;
            FOR r IN
                SELECT con.conname
                FROM pg_constraint con
                JOIN pg_class rel ON rel.oid = con.conrelid
                WHERE rel.relname = 'facebook_campaign_lead_attributions'
                  AND con.contype = 'f'
            LOOP
                EXECUTE format(
                    'ALTER TABLE facebook_campaign_lead_attributions DROP CONSTRAINT %I',
                    r.conname
                );
            END LOOP;
            ALTER TABLE facebook_campaign_lead_attributions
                ADD CONSTRAINT facebook_campaign_lead_attributions_lead_id_fkey
                FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE;
            ALTER TABLE facebook_campaign_lead_attributions
                ADD CONSTRAINT facebook_campaign_lead_attributions_facebook_campaign_id_fkey
                FOREIGN KEY (facebook_campaign_id) REFERENCES facebook_ad_campaigns(id)
                ON DELETE CASCADE;
        END $$;
    """)


def downgrade():
    op.execute("""
        ALTER TABLE facebook_campaign_lead_attributions
        DROP CONSTRAINT IF EXISTS facebook_campaign_lead_attributions_lead_id_fkey
    """)
    op.execute("""
        ALTER TABLE facebook_campaign_lead_attributions
        DROP CONSTRAINT IF EXISTS facebook_campaign_lead_attributions_facebook_campaign_id_fkey
    """)
    op.execute("""
        ALTER TABLE facebook_campaign_lead_attributions
        ADD CONSTRAINT facebook_campaign_lead_attributions_lead_id_fkey
        FOREIGN KEY (lead_id) REFERENCES leads(id)
    """)
    op.execute("""
        ALTER TABLE facebook_campaign_lead_attributions
        ADD CONSTRAINT facebook_campaign_lead_attributions_facebook_campaign_id_fkey
        FOREIGN KEY (facebook_campaign_id) REFERENCES facebook_ad_campaigns(id)
    """)
