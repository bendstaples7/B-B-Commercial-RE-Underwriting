"""Skip-trace sources registry + attempt history + lead ladder fields.

Revision ID: skp_trc_20260723
Revises: mail_can_20260722
"""
from alembic import op

revision = 'skp_trc_20260723'
down_revision = 'mail_can_20260722'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS skip_trace_config (
            id SERIAL PRIMARY KEY,
            sources JSONB NOT NULL DEFAULT '[]'::jsonb,
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        INSERT INTO skip_trace_config (sources)
        SELECT jsonb_build_array(
            jsonb_build_object(
                'id', 'manual_default',
                'label', 'Manual skip trace',
                'enabled', CAST(1 AS boolean),
                'kind', 'manual'
            )
        )
        WHERE NOT EXISTS (SELECT 1 FROM skip_trace_config LIMIT 1)
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS skip_trace_attempts (
            id SERIAL PRIMARY KEY,
            lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
            cycle INTEGER NOT NULL DEFAULT 1,
            source_id VARCHAR(64) NOT NULL,
            source_label VARCHAR(120) NOT NULL,
            started_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMP WITHOUT TIME ZONE,
            outcome VARCHAR(32) NOT NULL DEFAULT 'started',
            trigger VARCHAR(32) NOT NULL DEFAULT 'manual_move',
            mail_queue_item_id INTEGER,
            olc_order_id VARCHAR(64)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_skip_trace_attempts_lead_id
        ON skip_trace_attempts (lead_id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_skip_trace_attempts_lead_cycle
        ON skip_trace_attempts (lead_id, cycle)
    """)
    op.execute("""
        ALTER TABLE leads
        ADD COLUMN IF NOT EXISTS skip_trace_next_source_id VARCHAR(64)
    """)
    op.execute("""
        ALTER TABLE leads
        ADD COLUMN IF NOT EXISTS skip_trace_exhausted_at TIMESTAMP WITHOUT TIME ZONE
    """)
    op.execute("""
        ALTER TABLE leads
        ADD COLUMN IF NOT EXISTS skip_trace_cycle INTEGER NOT NULL DEFAULT 1
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_leads_skip_trace_exhausted_at
        ON leads (skip_trace_exhausted_at)
        WHERE skip_trace_exhausted_at IS NOT NULL
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_leads_skip_trace_exhausted_at")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS skip_trace_cycle")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS skip_trace_exhausted_at")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS skip_trace_next_source_id")
    op.execute("DROP TABLE IF EXISTS skip_trace_attempts")
    op.execute("DROP TABLE IF EXISTS skip_trace_config")
