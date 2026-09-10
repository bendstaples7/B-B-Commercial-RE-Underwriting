"""Clear placeholder owner names and unstage mail candidates.

Revision ID: gen_own_20260910
Revises: score_cal_20260907
Create Date: 2026-09-10

Assessor stubs such as ``Taxpayer of`` / ``TAXPAYER OF <address>`` were treated
as real people and could reach Ready to Mail. Deploy clears those flats,
unlinks matching placeholder owner contacts, removes staged mail-queue rows,
and demotes ``mail_ready`` → ``enrich_data`` so candidates leave the queue
before the next full rescore.

Uses Core SQL + ``is_placeholder_owner_name`` / ``contact_display_name``
(no nested create_app), matching ``joint_own_20260821``.
"""
from __future__ import annotations

from datetime import datetime

from alembic import op
import sqlalchemy as sa

revision = 'gen_own_20260910'
down_revision = 'score_cal_20260907'
branch_labels = None
depends_on = None

_MARKER = 'generic_owner_placeholder'


def _name_match_sql(*cols: str) -> str:
    """OR clauses for placeholder substrings / sole tokens on name columns."""
    parts: list[str] = []
    for col in cols:
        parts.extend([
            f"{col} ILIKE '%taxpayer%'",
            f"{col} ILIKE '%owner of record%'",
            f"{col} ILIKE '%unknown owner%'",
            f"{col} ILIKE '%current resident%'",
            f"{col} ILIKE '%for sale by owner%'",
            f"{col} ILIKE '%the taxpayer%'",
            f"{col} ILIKE '%owner unknown%'",
            f"{col} ILIKE '%name unknown%'",
            f"lower(trim(coalesce({col}, ''))) IN ('n/a', 'na', 'fsbo', 'taxpayer')",
        ])
    return ' OR '.join(parts)


def _concat_match_sql(first: str, last: str) -> str:
    """Match phrases that may split across first/last columns."""
    joined = (
        f"concat_ws(' ', "
        f"nullif(trim(coalesce({first}, '')), ''), "
        f"nullif(trim(coalesce({last}, '')), ''))"
    )
    return ' OR '.join([
        f"{joined} ILIKE '%taxpayer of%'",
        f"{joined} ILIKE '%owner of record%'",
        f"{joined} ILIKE '%unknown owner%'",
        f"{joined} ILIKE '%current resident%'",
        f"{joined} ILIKE '%for sale by owner%'",
        f"{joined} ILIKE '%the taxpayer%'",
        f"{joined} ILIKE '%owner unknown%'",
        f"{joined} ILIKE '%name unknown%'",
    ])


def upgrade():
    from app.services.plugins.owner_name_utils import (
        contact_display_name,
        is_placeholder_owner_name,
    )

    bind = op.get_bind()
    now = datetime.utcnow()
    healed_ids: list[int] = []

    lead_where = ' OR '.join([
        _name_match_sql(
            'owner_first_name', 'owner_last_name',
            'owner_2_first_name', 'owner_2_last_name',
        ),
        _concat_match_sql('owner_first_name', 'owner_last_name'),
        _concat_match_sql('owner_2_first_name', 'owner_2_last_name'),
    ])
    lead_rows = bind.execute(
        sa.text(
            f"""
            SELECT id,
                   owner_first_name, owner_last_name,
                   owner_2_first_name, owner_2_last_name,
                   recommended_action
            FROM leads
            WHERE {lead_where}
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

    contact_where = ' OR '.join([
        _name_match_sql('c.first_name', 'c.last_name'),
        _concat_match_sql('c.first_name', 'c.last_name'),
    ])
    contact_rows = bind.execute(
        sa.text(
            f"""
            SELECT pc.id AS link_id, pc.property_id, c.first_name, c.last_name
            FROM property_contacts pc
            JOIN contacts c ON c.id = pc.contact_id
            WHERE pc.role = 'owner'
              AND ({contact_where})
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
        marker_len = len(f'; {_MARKER}')
        bind.execute(
            sa.text(
                """
                UPDATE mail_queue_items
                SET status = 'removed',
                    updated_at = :now,
                    validation_error = CASE
                        WHEN validation_error IS NULL OR validation_error = ''
                        THEN :marker
                        ELSE left(validation_error, :keep)
                             || '; ' || :marker
                    END
                WHERE status = 'queued'
                  AND lead_id IN :ids
                """
            ).bindparams(sa.bindparam('ids', expanding=True)),
            {
                'now': now,
                'ids': healed_ids,
                'marker': _MARKER,
                'keep': 500 - marker_len,
            },
        )
        # Demote mail_ready for every healed lead (including contact-only heals).
        bind.execute(
            sa.text(
                """
                UPDATE leads
                SET recommended_action = CASE
                        WHEN recommended_action = 'mail_ready' THEN 'enrich_data'
                        ELSE recommended_action
                    END,
                    up_next_to_mail = false,
                    updated_at = :now
                WHERE id IN :ids
                """
            ).bindparams(sa.bindparam('ids', expanding=True)),
            {'now': now, 'ids': healed_ids},
        )

    print('generic_owner_heal healed_leads=%s' % len(healed_ids))


def downgrade():
    # Data heal is not reversible (placeholder names were not real identities).
    pass
