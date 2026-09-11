"""Add mail_queue_items status ``submitted`` (awaiting OLC confirm).

Revision ID: mail_sub_20260910
Revises: mail_stg_20260910
Create Date: 2026-09-10

After place_order, queue rows stay ``submitted`` until analytics sees the lead
on the OLC order contacts. Only then do we promote to ``sent`` and start
cadence / mail_sent evidence.
"""
from __future__ import annotations

from alembic import op

revision = 'mail_sub_20260910'
down_revision = 'mail_stg_20260910'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE mail_queue_status_enum "
        "ADD VALUE IF NOT EXISTS 'submitted'"
    )


def downgrade() -> None:
    # PostgreSQL cannot remove enum values safely; leave 'submitted' in place.
    pass
