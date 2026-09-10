"""Clear placeholder owner names and unstage mail candidates.

Revision ID: gen_own_20260910
Revises: score_cal_20260907
Create Date: 2026-09-10

Assessor stubs such as ``Taxpayer of`` / ``TAXPAYER OF <address>`` were treated
as real people and could reach Ready to Mail. Deploy clears those flats,
unlinks matching placeholder owner contacts, removes staged mail-queue rows,
and demotes ``mail_ready`` → ``enrich_data`` so candidates leave the queue
before the next full rescore.

Uses Core SQL + ``is_placeholder_owner_name`` (no nested create_app), matching
``joint_own_20260821``.
"""
from __future__ import annotations

from datetime import datetime

from alembic import op
import sqlalchemy as sa

revision = 'gen_own_20260910'
down_revision = 'score_cal_20260907'
branch_labels = None
depends_on = None


def upgrade():
    from app.services.plugins.owner_name_utils import (
        contact_display_name,
        is_placeholder_owner_name,
    )

    bind = op.get_bind()
    now = datetime.utcnow()
    healed_ids: list[int] = []

    lead_rows = bind.execute(
        sa.text(
            """
            SELECT id,
                   owner_first_name, owner_last_name,
                   owner_2_first_name, owner_2_last_name,
                   recommended_action
            FROM leads
            WHERE owner_first_name ILIKE '%taxpayer%'
               OR owner_last_name ILIKE '%taxpayer%'
               OR owner_first_name ILIKE '%owner of record%'
               OR owner_last_name ILIKE '%owner of record%'
               OR owner_first_name ILIKE '%unknown owner%'
               OR owner_last_name ILIKE '%unknown owner%'
               OR owner_first_name ILIKE '%current resident%'
               OR owner_last_name ILIKE '%current resident%'
               OR owner_first_name ILIKE '%for sale by owner%'
               OR owner_last_name ILIKE '%for sale by owner%'
               OR lower(trim(coalesce(owner_first_name, ''))) IN ('n/a', 'na', 'fsbo', 'taxpayer')
               OR lower(trim(coalesce(owner_last_name, ''))) IN ('n/a', 'na', 'fsbo', 'taxpayer')
               OR owner_2_first_name ILIKE '%taxpayer%'
               OR owner_2_last_name ILIKE '%taxpayer%'
            """
        )
    ).mappings().all()

    for row in lead_rows:
        lead_id = int(row['id'])
        flat = contact_display_name(row['owner_first_name'], row['owner_last_name'])
        o2 = contact_display_name(row['owner_2_first_name'], row['owner_2_last_name'])
        clear_flat = bool(flat) and is_placeholder_owner_name(flat)
        clear_o2 = bool(o2) and is_placeholder_owner_name(o2)
        if not clear_flat and not clear_o2:
            continue

        params = {'id': lead_id, 'now': now}
        sets = ['updated_at = :now']
        if clear_flat:
            sets.extend([
                'owner_first_name = NULL',
                'owner_last_name = NULL',
            ])
        if clear_o2:
            sets.extend([
                'owner_2_first_name = NULL',
                'owner_2_last_name = NULL',
            ])
        if (row['recommended_action'] or '') == 'mail_ready':
            sets.append("recommended_action = 'enrich_data'")
        bind.execute(
            sa.text(f"UPDATE leads SET {', '.join(sets)} WHERE id = :id"),
            params,
        )
        healed_ids.append(lead_id)

    # Also unlink placeholder owner contacts (may exist without matching flats).
    contact_rows = bind.execute(
        sa.text(
            """
            SELECT pc.id AS link_id, pc.property_id, c.first_name, c.last_name
            FROM property_contacts pc
            JOIN contacts c ON c.id = pc.contact_id
            WHERE pc.role = 'owner'
              AND (
                c.first_name ILIKE '%taxpayer%'
                OR c.last_name ILIKE '%taxpayer%'
                OR c.first_name ILIKE '%owner of record%'
                OR c.last_name ILIKE '%owner of record%'
                OR lower(trim(coalesce(c.first_name, ''))) IN ('n/a', 'na', 'fsbo', 'taxpayer')
                OR lower(trim(coalesce(c.last_name, ''))) IN ('n/a', 'na', 'fsbo', 'taxpayer')
              )
            """
        )
    ).mappings().all()
    for row in contact_rows:
        display = contact_display_name(row['first_name'], row['last_name'])
        if not display or not is_placeholder_owner_name(display):
            continue
        bind.execute(
            sa.text('DELETE FROM property_contacts WHERE id = :id'),
            {'id': row['link_id']},
        )
        pid = int(row['property_id'])
        if pid not in healed_ids:
            healed_ids.append(pid)

    if healed_ids:
        # Unstage Ready-to-Mail items for healed leads.
        bind.execute(
            sa.text(
                """
                UPDATE mail_queue_items
                SET status = 'removed',
                    updated_at = :now,
                    validation_error = CASE
                        WHEN validation_error IS NULL OR validation_error = ''
                        THEN 'generic_owner_placeholder'
                        ELSE validation_error || '; generic_owner_placeholder'
                    END
                WHERE status = 'queued'
                  AND lead_id IN :ids
                """
            ).bindparams(sa.bindparam('ids', expanding=True)),
            {'now': now, 'ids': healed_ids},
        )
        bind.execute(
            sa.text(
                """
                UPDATE leads
                SET up_next_to_mail = false, updated_at = :now
                WHERE id IN :ids
                """
            ).bindparams(sa.bindparam('ids', expanding=True)),
            {'now': now, 'ids': healed_ids},
        )

    print('generic_owner_heal healed_leads=%s' % len(healed_ids))


def downgrade():
    # Data heal is not reversible (placeholder names were not real identities).
    pass
