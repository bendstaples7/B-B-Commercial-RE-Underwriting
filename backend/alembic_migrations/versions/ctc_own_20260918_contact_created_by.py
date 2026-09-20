"""Stamp contacts.created_by_user_id so unlinked PII is not world-readable.

Revision ID: ctc_own_20260918
Revises: act_mtg_20260919
Create Date: 2026-09-18

Unlinked contacts had no owner column, so GET/PUT/DELETE by id was open to any
authenticated user. New rows record the creating user; existing unlinked rows
stay NULL and are fail-closed except for admins.
"""
from __future__ import annotations

from alembic import op

revision = 'ctc_own_20260918'
down_revision = 'act_mtg_20260919'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE contacts
        ADD COLUMN IF NOT EXISTS created_by_user_id VARCHAR(255)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_contacts_created_by_user_id
        ON contacts (created_by_user_id)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_contacts_created_by_user_id")
    op.execute("ALTER TABLE contacts DROP COLUMN IF EXISTS created_by_user_id")
