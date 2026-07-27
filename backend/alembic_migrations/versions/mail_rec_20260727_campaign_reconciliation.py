"""Add mail campaign submit reconciliation + address feedback rollup columns.

Revision ID: mail_rec_20260727
Revises: wh_skip_20260723
Create Date: 2026-07-27
"""
from alembic import op

revision = 'mail_rec_20260727'
down_revision = 'wh_skip_20260723'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE mail_campaigns
        ADD COLUMN IF NOT EXISTS staged_count INTEGER
    """)
    op.execute("""
        ALTER TABLE mail_campaigns
        ADD COLUMN IF NOT EXISTS submitted_count INTEGER
    """)
    op.execute("""
        ALTER TABLE mail_campaigns
        ADD COLUMN IF NOT EXISTS invalid_at_submit_count INTEGER
    """)
    op.execute("""
        ALTER TABLE mail_campaigns
        ADD COLUMN IF NOT EXISTS submit_drop_summary JSON
    """)
    op.execute("""
        ALTER TABLE mail_campaigns
        ADD COLUMN IF NOT EXISTS address_feedback_summary JSON
    """)
    # Backfill reconciliation from attached queue rows for existing campaigns.
    # invalid_at_submit matches runtime drops: invalid_address + failed (e.g. lead missing).
    # Do not rewrite historical lead_count — that remains the campaign denominator.
    op.execute("""
        UPDATE mail_campaigns AS c
        SET
            staged_count = COALESCE(q.staged, c.lead_count),
            submitted_count = COALESCE(q.sent, c.lead_count),
            invalid_at_submit_count = COALESCE(q.invalid_at_submit, 0)
        FROM (
            SELECT
                campaign_id,
                COUNT(*)::int AS staged,
                COUNT(*) FILTER (WHERE status = 'sent')::int AS sent,
                COUNT(*) FILTER (
                    WHERE status IN ('invalid_address', 'failed')
                )::int AS invalid_at_submit
            FROM mail_queue_items
            WHERE campaign_id IS NOT NULL
            GROUP BY campaign_id
        ) AS q
        WHERE c.id = q.campaign_id
          AND c.staged_count IS NULL
    """)
    op.execute("""
        UPDATE mail_campaigns
        SET
            staged_count = COALESCE(staged_count, lead_count),
            submitted_count = COALESCE(submitted_count, lead_count),
            invalid_at_submit_count = COALESCE(invalid_at_submit_count, 0)
        WHERE staged_count IS NULL
           OR submitted_count IS NULL
           OR invalid_at_submit_count IS NULL
    """)


def downgrade():
    op.execute('ALTER TABLE mail_campaigns DROP COLUMN IF EXISTS address_feedback_summary')
    op.execute('ALTER TABLE mail_campaigns DROP COLUMN IF EXISTS submit_drop_summary')
    op.execute('ALTER TABLE mail_campaigns DROP COLUMN IF EXISTS invalid_at_submit_count')
    op.execute('ALTER TABLE mail_campaigns DROP COLUMN IF EXISTS submitted_count')
    op.execute('ALTER TABLE mail_campaigns DROP COLUMN IF EXISTS staged_count')
