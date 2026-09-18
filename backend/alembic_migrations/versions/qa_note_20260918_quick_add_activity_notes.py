"""Backfill Activity notes for quick-add leads missing note_added.

Revision ID: qa_note_20260918
Revises: ask_prc_20260918
Create Date: 2026-09-18

Quick Add always wrote the walk-by block to ``leads.deal_description``, but
``note_added`` timeline rows were created only when the optional note field
was non-empty. Activity then showed later status/GIS/skip-trace rows and hid
the field capture. Deploy inserts a ``note_added`` from deal_description for
quick-add leads that still lack a quick-add-sourced note.
"""
from __future__ import annotations

from alembic import op

revision = 'qa_note_20260918'
down_revision = 'ask_prc_20260918'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return
    op.execute(
        """
        INSERT INTO lead_timeline_entries (
            lead_id, event_type, occurred_at, source, actor, summary,
            metadata, is_deleted, created_at
        )
        SELECT
            l.id,
            'note_added',
            COALESCE(
                (
                    SELECT e.occurred_at
                    FROM lead_timeline_entries e
                    WHERE e.lead_id = l.id
                      AND e.event_type = 'lead_imported'
                      AND e.is_deleted = false
                    ORDER BY e.occurred_at ASC
                    LIMIT 1
                ),
                l.created_at,
                timezone('utc', now())
            ),
            'manual',
            LEFT(COALESCE(NULLIF(l.owner_user_id, ''), 'quick_add'), 100),
            LEFT(
                COALESCE(NULLIF(BTRIM(l.deal_description), ''), 'Walk-by capture'),
                500
            ),
            jsonb_build_object(
                'body', COALESCE(NULLIF(BTRIM(l.deal_description), ''), 'Walk-by capture'),
                'source', 'quick_add',
                'backfill', 'qa_note_20260918'
            ),
            false,
            timezone('utc', now())
        FROM leads l
        WHERE l.data_source = 'quick_add'
          AND COALESCE(NULLIF(BTRIM(l.deal_description), ''), '') <> ''
          AND NOT EXISTS (
              SELECT 1
              FROM lead_timeline_entries e
              WHERE e.lead_id = l.id
                AND e.is_deleted = false
                AND e.event_type = 'note_added'
                AND COALESCE(e.metadata->>'source', '') = 'quick_add'
          )
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return
    op.execute(
        """
        DELETE FROM lead_timeline_entries
        WHERE event_type = 'note_added'
          AND COALESCE(metadata->>'backfill', '') = 'qa_note_20260918'
        """
    )
