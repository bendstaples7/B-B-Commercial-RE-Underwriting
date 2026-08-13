"""Add leads.note_property_facts and backfill from HubSpot timeline notes/calls.

Revision ID: note_pf_20260812
Revises: aka_situs_20260729
Create Date: 2026-08-12

Schema: JSONB column for note-derived units + unit mix.
Data: idempotent chunked backfill via ``apply_note_facts_from_timeline``
(Deploy runs this — no manual script).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session


revision = 'note_pf_20260812'
down_revision = 'aka_situs_20260729'
branch_labels = None
depends_on = None

_BACKFILL_CHUNK = 100


def upgrade():
    op.execute("""
        ALTER TABLE leads
        ADD COLUMN IF NOT EXISTS note_property_facts JSONB
    """)

    bind = op.get_bind()
    session = Session(bind=bind)

    from app.models.lead import Lead
    from app.services.helpers.note_property_facts import apply_note_facts_from_timeline

    last_lead_id = 0
    processed = 0
    while True:
        rows = session.execute(
            sa.text(
                """
                SELECT DISTINCT lead_id
                FROM lead_timeline_entries
                WHERE is_deleted = false
                  AND event_type IN ('hubspot_note', 'hubspot_call')
                  AND lead_id > :last_lead_id
                ORDER BY lead_id
                LIMIT :limit
                """
            ),
            {'last_lead_id': last_lead_id, 'limit': _BACKFILL_CHUNK},
        ).all()
        if not rows:
            break

        for row in rows:
            lead_id = int(row[0])
            last_lead_id = lead_id
            processed += 1
            lead = session.get(Lead, lead_id)
            if lead is None:
                continue
            updated = apply_note_facts_from_timeline(lead)
            if updated:
                session.add(lead)
            if processed % _BACKFILL_CHUNK == 0:
                session.commit()

    session.commit()


def downgrade():
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS note_property_facts")
