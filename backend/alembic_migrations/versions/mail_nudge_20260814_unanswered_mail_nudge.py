"""Add unanswered_mail_nudge_dismissed_count for Keep-calling dismiss.

Revision ID: mail_nudge_20260814
Revises: spa_boot_20260813
Create Date: 2026-08-14
"""
from alembic import op

revision = 'mail_nudge_20260814'
down_revision = 'spa_boot_20260813'
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE leads
        ADD COLUMN IF NOT EXISTS unanswered_mail_nudge_dismissed_count INTEGER
    """)
    op.execute("""
        ALTER TABLE leads
        ADD COLUMN IF NOT EXISTS prefer_direct_mail BOOLEAN NOT NULL DEFAULT FALSE
    """)


def downgrade():
    op.execute("""
        ALTER TABLE leads
        DROP COLUMN IF EXISTS prefer_direct_mail
    """)
    op.execute("""
        ALTER TABLE leads
        DROP COLUMN IF EXISTS unanswered_mail_nudge_dismissed_count
    """)
