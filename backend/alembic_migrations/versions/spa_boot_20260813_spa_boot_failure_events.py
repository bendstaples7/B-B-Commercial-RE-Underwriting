"""Add spa_boot_failure_events for blank-SPA phone-home beacons.

Revision ID: spa_boot_20260813
Revises: note_pf_20260812
Create Date: 2026-08-13
"""
from alembic import op

revision = 'spa_boot_20260813'
down_revision = 'note_pf_20260812'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE IF NOT EXISTS spa_boot_failure_events (
            id SERIAL PRIMARY KEY,
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL,
            ip_hash VARCHAR(64),
            href VARCHAR(1024),
            reason VARCHAR(128),
            user_agent VARCHAR(512),
            asset_hints JSONB
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_spa_boot_failure_events_created_at
        ON spa_boot_failure_events (created_at)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_spa_boot_failure_events_ip_hash
        ON spa_boot_failure_events (ip_hash)
    """)


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_spa_boot_failure_events_ip_hash")
    op.execute("DROP INDEX IF EXISTS ix_spa_boot_failure_events_created_at")
    op.execute("DROP TABLE IF EXISTS spa_boot_failure_events")
