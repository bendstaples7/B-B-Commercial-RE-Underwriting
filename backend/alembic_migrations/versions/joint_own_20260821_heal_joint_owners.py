"""Add property_overview_changed; restore Edwin on 11130; heal jammed co-owners.

Revision ID: joint_own_20260821
Revises: cat_lock_20260819
Create Date: 2026-08-21

Uses Core SQL + owner_name_utils (no nested create_app). Enum ADD VALUE matches
``cat_lock_20260819`` (Postgres 12+ allows IF NOT EXISTS in a transaction).

Live jammed GIS rows (``A & B`` / ``A and B`` in owner_first_name) get empty
``owner_2_*`` filled and missing owner contacts upserted without renaming the
primary flat field (avoids ``uq_leads_owner_normalized_street`` collisions).
"""
from __future__ import annotations

from datetime import datetime

from alembic import op
import sqlalchemy as sa

revision = 'joint_own_20260821'
down_revision = 'cat_lock_20260819'
branch_labels = None
depends_on = None

_EDWIN_LEAD_ID = 11130
_EDWIN_FIRST = 'Edwin'
_EDWIN_LAST = 'Miller'


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        op.execute(
            "ALTER TYPE timeline_event_type_enum "
            "ADD VALUE IF NOT EXISTS 'property_overview_changed'"
        )

    _restore_edwin_miller(bind)
    _heal_jammed_owner_flats(bind)


def _owner_contact_exists(bind, lead_id: int, first: str, last: str) -> bool:
    row = bind.execute(
        sa.text(
            """
            SELECT c.id
            FROM property_contacts pc
            JOIN contacts c ON c.id = pc.contact_id
            WHERE pc.property_id = :pid
              AND pc.role = 'owner'
              AND lower(trim(coalesce(c.first_name, ''))) = lower(:f)
              AND lower(trim(coalesce(c.last_name, ''))) = lower(:l)
            LIMIT 1
            """
        ),
        {'pid': lead_id, 'f': first, 'l': last},
    ).first()
    return row is not None


def _ensure_owner_contact(bind, lead_id: int, first: str, last: str) -> None:
    if not (first or last):
        return
    if _owner_contact_exists(bind, lead_id, first, last or ''):
        return
    now = datetime.utcnow()
    contact_id = bind.execute(
        sa.text(
            """
            INSERT INTO contacts (
                first_name, last_name, role, created_at, updated_at,
                name_locked, keep_on_gis
            )
            VALUES (:f, :l, 'owner', :now, :now, false, false)
            RETURNING id
            """
        ),
        {'f': first, 'l': last or None, 'now': now},
    ).scalar()
    bind.execute(
        sa.text(
            """
            INSERT INTO property_contacts (property_id, contact_id, role, is_primary)
            VALUES (:pid, :cid, 'owner', false)
            """
        ),
        {'pid': lead_id, 'cid': contact_id},
    )


def _restore_edwin_miller(bind) -> None:
    """Idempotent: ensure lead 11130 has Edwin Miller as owner_2 + contact."""
    lead = bind.execute(
        sa.text(
            'SELECT id, owner_2_first_name, owner_2_last_name '
            'FROM leads WHERE id = :id'
        ),
        {'id': _EDWIN_LEAD_ID},
    ).mappings().first()
    if lead is None:
        return

    if not (lead['owner_2_first_name'] or '').strip():
        bind.execute(
            sa.text(
                'UPDATE leads SET owner_2_first_name = :f, owner_2_last_name = :l, '
                'updated_at = :now WHERE id = :id'
            ),
            {
                'f': _EDWIN_FIRST,
                'l': _EDWIN_LAST,
                'now': datetime.utcnow(),
                'id': _EDWIN_LEAD_ID,
            },
        )

    _ensure_owner_contact(bind, _EDWIN_LEAD_ID, _EDWIN_FIRST, _EDWIN_LAST)


def _heal_jammed_owner_flats(bind) -> None:
    """Fill empty owner_2 + contacts for jammed primary names (no primary rename)."""
    # Importable without Flask app context.
    from app.services.plugins.owner_name_utils import split_joint_person_owner_name

    rows = bind.execute(
        sa.text(
            """
            SELECT id, owner_first_name, owner_last_name,
                   owner_2_first_name, owner_2_last_name
            FROM leads
            WHERE owner_first_name IS NOT NULL
              AND (
                owner_first_name ILIKE '% and %'
                OR owner_first_name ILIKE '% & %'
              )
            ORDER BY id
            """
        )
    ).mappings().all()

    now = datetime.utcnow()
    for row in rows:
        people = split_joint_person_owner_name(
            row['owner_first_name'], row['owner_last_name'],
        )
        if len(people) < 2:
            continue
        second_first, second_last = people[1]
        o2_empty = not (
            (row['owner_2_first_name'] or '').strip()
            or (row['owner_2_last_name'] or '').strip()
        )
        if o2_empty and (second_first or second_last):
            bind.execute(
                sa.text(
                    'UPDATE leads SET owner_2_first_name = :f, owner_2_last_name = :l, '
                    'updated_at = :now WHERE id = :id'
                ),
                {
                    'f': second_first,
                    'l': second_last,
                    'now': now,
                    'id': row['id'],
                },
            )
        for first, last in people:
            _ensure_owner_contact(bind, row['id'], first or '', last or '')


def downgrade():
    pass
