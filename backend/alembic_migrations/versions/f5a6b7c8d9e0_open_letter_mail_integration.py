"""Open Letter Connect mail queue and campaign tables.

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-07-01

Adds OLC config, mail queue, mail campaigns, and timeline event types for mail.
"""
from alembic import op

revision = 'f5a6b7c8d9e0'
down_revision = 'e4f5a6b7c8d9'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE mail_campaign_status_enum AS ENUM (
                'pending', 'submitted', 'processing', 'mailed', 'failed'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS open_letter_config (
            id SERIAL PRIMARY KEY,
            encrypted_api_token TEXT NOT NULL,
            use_demo_api BOOLEAN NOT NULL DEFAULT FALSE,
            default_product_id INTEGER,
            default_template_id INTEGER,
            default_template_name VARCHAR(255),
            batch_minimum INTEGER NOT NULL DEFAULT 50,
            allow_send_below_minimum BOOLEAN NOT NULL DEFAULT FALSE,
            return_address JSONB,
            estimated_cost_per_piece NUMERIC(10, 4),
            created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),
            updated_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS mail_campaigns (
            id SERIAL PRIMARY KEY,
            olc_order_id VARCHAR(50),
            status mail_campaign_status_enum NOT NULL DEFAULT 'pending',
            lead_count INTEGER NOT NULL DEFAULT 0,
            cost NUMERIC(12, 4),
            cost_per_piece NUMERIC(10, 4),
            product_id INTEGER,
            template_id INTEGER,
            template_name VARCHAR(255),
            delivery_stats JSONB,
            scan_stats JSONB,
            response_count INTEGER NOT NULL DEFAULT 0,
            created_by VARCHAR(100) NOT NULL,
            submitted_at TIMESTAMP,
            error_message TEXT,
            analytics_synced_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),
            updated_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
        )
    """)
    op.execute('CREATE INDEX IF NOT EXISTS ix_mail_campaigns_olc_order_id ON mail_campaigns (olc_order_id)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_mail_campaigns_status ON mail_campaigns (status)')

    op.execute("""
        DO $$ BEGIN
            CREATE TYPE mail_queue_status_enum AS ENUM (
                'queued', 'invalid_address', 'removed', 'sent', 'failed'
            );
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS mail_queue_items (
            id SERIAL PRIMARY KEY,
            lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
            user_id VARCHAR(100) NOT NULL,
            status mail_queue_status_enum NOT NULL DEFAULT 'queued',
            validation_error VARCHAR(500),
            campaign_id INTEGER REFERENCES mail_campaigns(id) ON DELETE SET NULL,
            created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc'),
            updated_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
        )
    """)
    op.execute('CREATE INDEX IF NOT EXISTS ix_mail_queue_items_lead_id ON mail_queue_items (lead_id)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_mail_queue_items_user_id ON mail_queue_items (user_id)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_mail_queue_items_status ON mail_queue_items (status)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_mail_queue_items_campaign_id ON mail_queue_items (campaign_id)')
    op.execute('CREATE INDEX IF NOT EXISTS ix_mail_queue_lead_status ON mail_queue_items (lead_id, status)')
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_mail_queue_lead_queued
        ON mail_queue_items (lead_id)
        WHERE status = 'queued'
    """)

    for event in ('mail_queued', 'mail_sent', 'mail_delivered'):
        op.execute(
            f"ALTER TYPE timeline_event_type_enum ADD VALUE IF NOT EXISTS '{event}'"
        )


def downgrade():
    op.execute('DROP INDEX IF EXISTS uq_mail_queue_lead_queued')
    op.execute('DROP INDEX IF EXISTS ix_mail_queue_lead_status')
    op.execute('DROP INDEX IF EXISTS ix_mail_queue_items_campaign_id')
    op.execute('DROP INDEX IF EXISTS ix_mail_queue_items_status')
    op.execute('DROP INDEX IF EXISTS ix_mail_queue_items_user_id')
    op.execute('DROP INDEX IF EXISTS ix_mail_queue_items_lead_id')
    op.execute('DROP TABLE IF EXISTS mail_queue_items')
    op.execute('DROP TYPE IF EXISTS mail_queue_status_enum')
    op.execute('DROP INDEX IF EXISTS ix_mail_campaigns_status')
    op.execute('DROP INDEX IF EXISTS ix_mail_campaigns_olc_order_id')
    op.execute('DROP TABLE IF EXISTS mail_campaigns')
    op.execute('DROP TYPE IF EXISTS mail_campaign_status_enum')
    op.execute('DROP TABLE IF EXISTS open_letter_config')
