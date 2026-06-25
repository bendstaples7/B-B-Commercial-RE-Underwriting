"""Add leads.normalized_street column for dedup identity.

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
Create Date: 2026-06-22

Adds persisted building-level street key. Run merge before the follow-up
migration that adds unique indexes:

    python scripts/merge_duplicate_leads.py --mode dedup
    flask db upgrade
"""

import os
import sys

from alembic import op
from sqlalchemy import text

revision = 'f8a9b0c1d2e3'
down_revision = 'e7f8a9b0c1d2'
branch_labels = None
depends_on = None


def _backfill_normalized_street(connection) -> None:
    backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    from app.services.lead_merge_utils import dedup_street_key

    rows = connection.execute(text(
        """
        SELECT id, property_street
        FROM leads
        WHERE property_street IS NOT NULL AND property_street != ''
        """
    ))
    batch: list[dict] = []
    for row in rows:
        key = dedup_street_key(row.property_street)
        if not key:
            continue
        batch.append({'key': key, 'id': row.id})
        if len(batch) >= 2000:
            connection.execute(
                text("UPDATE leads SET normalized_street = :key WHERE id = :id"),
                batch,
            )
            batch.clear()
    if batch:
        connection.execute(
            text("UPDATE leads SET normalized_street = :key WHERE id = :id"),
            batch,
        )


def upgrade():
    op.execute("""
        ALTER TABLE leads
        ADD COLUMN IF NOT EXISTS normalized_street VARCHAR(500)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_leads_normalized_street
        ON leads (normalized_street)
    """)

    _backfill_normalized_street(op.get_bind())


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_leads_normalized_street")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS normalized_street")
