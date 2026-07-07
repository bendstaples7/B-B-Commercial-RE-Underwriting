"""Motivation signal pipeline — signals, prospect candidates, lead denorm columns.

Revision ID: h7i8j9k0l1m2
Revises: g6a7b8c9d0e1
Create Date: 2026-07-06
"""
from alembic import op

revision = 'h7i8j9k0l1m2'
down_revision = 'g6a7b8c9d0e1'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS motivation_signals (
            id SERIAL PRIMARY KEY,
            lead_id INTEGER REFERENCES leads(id) ON DELETE CASCADE,
            signal_type VARCHAR(64) NOT NULL,
            severity VARCHAR(16) NOT NULL,
            points DOUBLE PRECISION NOT NULL DEFAULT 0,
            source VARCHAR(32) NOT NULL,
            source_dataset VARCHAR(64),
            evidence_key VARCHAR(255),
            evidence JSONB,
            detected_at TIMESTAMP NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMP,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            CONSTRAINT uq_motivation_signal_lead_type_key
                UNIQUE (lead_id, signal_type, evidence_key)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_motivation_signals_lead_id
        ON motivation_signals(lead_id)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS prospect_candidates (
            id SERIAL PRIMARY KEY,
            owner_user_id VARCHAR(36) NOT NULL,
            pin VARCHAR(50),
            property_street VARCHAR(500),
            property_city VARCHAR(100),
            property_state VARCHAR(50),
            latitude DOUBLE PRECISION,
            longitude DOUBLE PRECISION,
            primary_signal_type VARCHAR(64) NOT NULL,
            motivation_score DOUBLE PRECISION NOT NULL DEFAULT 0,
            signals JSONB,
            source_feed VARCHAR(64) NOT NULL,
            external_key VARCHAR(255) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            duplicate_lead_id INTEGER REFERENCES leads(id) ON DELETE SET NULL,
            imported_lead_id INTEGER REFERENCES leads(id) ON DELETE SET NULL,
            reviewed_at TIMESTAMP,
            reviewed_by VARCHAR(36),
            rejection_reason TEXT,
            raw_record JSONB,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_prospect_feed_external_key
                UNIQUE (source_feed, external_key)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_prospect_candidates_owner_user_id
        ON prospect_candidates(owner_user_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_prospect_candidates_pin
        ON prospect_candidates(pin)
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS prospect_feed_state (
            id SERIAL PRIMARY KEY,
            feed_name VARCHAR(64) NOT NULL UNIQUE,
            last_synced_at TIMESTAMP,
            cursor VARCHAR(255),
            rows_processed INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS prospect_area_filters (
            id SERIAL PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL UNIQUE,
            enabled BOOLEAN NOT NULL DEFAULT FALSE,
            label VARCHAR(255),
            geometry JSONB,
            updated_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_prospect_area_filters_user_id
        ON prospect_area_filters(user_id)
    """)

    op.execute("""
        ALTER TABLE leads
        ADD COLUMN IF NOT EXISTS motivation_score DOUBLE PRECISION DEFAULT 0
    """)
    op.execute("""
        ALTER TABLE leads
        ADD COLUMN IF NOT EXISTS motivation_signal_summary JSONB
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_leads_motivation_score
        ON leads(motivation_score)
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_leads_motivation_score")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS motivation_signal_summary")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS motivation_score")
    op.execute("DROP INDEX IF EXISTS ix_prospect_area_filters_user_id")
    op.execute("DROP TABLE IF EXISTS prospect_area_filters")
    op.execute("DROP TABLE IF EXISTS prospect_feed_state")
    op.execute("DROP INDEX IF EXISTS ix_prospect_candidates_pin")
    op.execute("DROP INDEX IF EXISTS ix_prospect_candidates_owner_user_id")
    op.execute("DROP TABLE IF EXISTS prospect_candidates")
    op.execute("DROP INDEX IF EXISTS ix_motivation_signals_lead_id")
    op.execute("DROP TABLE IF EXISTS motivation_signals")
