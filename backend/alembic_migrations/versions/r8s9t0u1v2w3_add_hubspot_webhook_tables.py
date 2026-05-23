"""Add HubSpot webhook tables and encrypted_client_secret column.

Revision ID: r8s9t0u1v2w3
Revises: q7r8s9t0u1v2
Create Date: 2026-05-21 00:00:00.000000

Changes:
  - Create enum type webhook_log_status_enum
  - Create table hubspot_webhook_logs
  - Create table hubspot_sync_runs
  - Create table hubspot_platform_writes
  - Add indexes on hubspot_webhook_logs and hubspot_platform_writes
  - Add encrypted_client_secret TEXT column to hubspot_config
"""
from alembic import op


revision = 'r8s9t0u1v2w3'
down_revision = 'q7r8s9t0u1v2'
branch_labels = None
depends_on = None


def upgrade():
    # Create the webhook log status enum (idempotent)
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE webhook_log_status_enum AS ENUM (
                'pending', 'processing', 'processed', 'failed',
                'deduplicated', 'loop_suppressed'
            );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
    """)

    # Create hubspot_webhook_logs table
    op.execute("""
        CREATE TABLE IF NOT EXISTS hubspot_webhook_logs (
            id SERIAL PRIMARY KEY,
            hubspot_object_type VARCHAR(50) NOT NULL,
            hubspot_object_id VARCHAR(50) NOT NULL,
            event_type VARCHAR(100) NOT NULL,
            subscription_type VARCHAR(100),
            raw_payload JSONB NOT NULL,
            status webhook_log_status_enum NOT NULL DEFAULT 'pending',
            error_message TEXT,
            superseded_by_log_id INTEGER REFERENCES hubspot_webhook_logs(id),
            received_at TIMESTAMP NOT NULL DEFAULT NOW(),
            processed_at TIMESTAMP
        )
    """)

    # Indexes on hubspot_webhook_logs
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_webhook_log_object
        ON hubspot_webhook_logs(hubspot_object_type, hubspot_object_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_webhook_log_status
        ON hubspot_webhook_logs(status)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_webhook_log_received
        ON hubspot_webhook_logs(received_at)
    """)

    # Create hubspot_sync_runs table
    op.execute("""
        CREATE TABLE IF NOT EXISTS hubspot_sync_runs (
            id SERIAL PRIMARY KEY,
            trigger VARCHAR(50) NOT NULL DEFAULT 'webhook',
            object_type VARCHAR(50) NOT NULL,
            hubspot_id VARCHAR(50) NOT NULL,
            upsert_result VARCHAR(20),
            webhook_log_id INTEGER REFERENCES hubspot_webhook_logs(id),
            processed_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)

    # Create hubspot_platform_writes table
    op.execute("""
        CREATE TABLE IF NOT EXISTS hubspot_platform_writes (
            id SERIAL PRIMARY KEY,
            object_type VARCHAR(50) NOT NULL,
            hubspot_id VARCHAR(50) NOT NULL,
            written_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """)

    # Index on hubspot_platform_writes for loop guard lookups
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_platform_writes_lookup
        ON hubspot_platform_writes(object_type, hubspot_id, written_at)
    """)

    # Add encrypted_client_secret to hubspot_config
    op.execute("""
        ALTER TABLE hubspot_config
        ADD COLUMN IF NOT EXISTS encrypted_client_secret TEXT
    """)


def downgrade():
    op.execute("ALTER TABLE hubspot_config DROP COLUMN IF EXISTS encrypted_client_secret")
    op.execute("DROP INDEX IF EXISTS ix_platform_writes_lookup")
    op.execute("DROP TABLE IF EXISTS hubspot_platform_writes")
    op.execute("DROP TABLE IF EXISTS hubspot_sync_runs")
    op.execute("DROP INDEX IF EXISTS ix_webhook_log_received")
    op.execute("DROP INDEX IF EXISTS ix_webhook_log_status")
    op.execute("DROP INDEX IF EXISTS ix_webhook_log_object")
    op.execute("DROP TABLE IF EXISTS hubspot_webhook_logs")
    op.execute("DROP TYPE IF EXISTS webhook_log_status_enum")
