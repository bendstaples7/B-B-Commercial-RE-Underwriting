"""Upsert lead_status pipeline stage weights (preserve custom; delete legacy only).

Revision ID: lead_stg_20260722
Revises: rtm_idx_20260721

Stage definitions are snapshotted here so later edits to the runtime module
do not change this already-released revision.
"""

from alembic import op
import sqlalchemy as sa


revision = 'lead_stg_20260722'
down_revision = 'rtm_idx_20260721'
branch_labels = None
depends_on = None

# Frozen snapshot of lead_pipeline_stages.LEAD_PIPELINE_STAGES at this revision.
_STAGES = (
    ('awaiting_skip_trace', 0, -10.0),
    ('skip_trace', 1, -5.0),
    ('mailing_no_contact_made', 2, 0.0),
    ('mailing_contacted_no_interest', 3, -15.0),
    ('mailing_contacted_interested', 4, 20.0),
    ('negotiating_remote', 5, 35.0),
    ('in_person_appointment', 6, 45.0),
    ('offer_delivered', 7, 55.0),
    ('deprioritize', 8, -25.0),
    ('deal_won', 9, 0.0),
    ('deal_lost', 10, -30.0),
    ('suppressed', 11, -40.0),
    ('do_not_contact', 12, -40.0),
)

# Explicit retired multifamily/CRM labels only — never delete unknown custom rows.
_LEGACY_STAGE_NAMES = (
    'Draft',
    'Lead',
    'Qualification',
    'Proposal',
    'Negotiation',
    'Closed Won',
    'Closed Lost',
)

_LEGACY_DOWNGRADE = (
    ('Draft', 0, 0.5),
    ('Lead', 1, 1.0),
    ('Qualification', 2, 3.0),
    ('Proposal', 3, 5.0),
    ('Negotiation', 4, 8.0),
    ('Closed Won', 5, 10.0),
    ('Closed Lost', 6, 0.0),
)


def upgrade():
    conn = op.get_bind()
    for stage_name in _LEGACY_STAGE_NAMES:
        conn.execute(
            sa.text('DELETE FROM pipeline_stage_configs WHERE stage_name = :n'),
            {'n': stage_name},
        )

    # Avoid unique(order) collisions while rewriting: park known rows first.
    for i, (stage_name, _order, _weight) in enumerate(_STAGES):
        conn.execute(
            sa.text(
                'UPDATE pipeline_stage_configs '
                'SET "order" = :tmp_order '
                'WHERE stage_name = :stage_name'
            ),
            {'stage_name': stage_name, 'tmp_order': 10_000 + i},
        )

    for stage_name, order, weight in _STAGES:
        row = conn.execute(
            sa.text(
                'SELECT id FROM pipeline_stage_configs WHERE stage_name = :n'
            ),
            {'n': stage_name},
        ).fetchone()
        if row:
            conn.execute(
                sa.text(
                    'UPDATE pipeline_stage_configs '
                    'SET "order" = :order, weight = :weight '
                    'WHERE stage_name = :stage_name'
                ),
                {
                    'stage_name': stage_name,
                    'order': order,
                    'weight': weight,
                },
            )
        else:
            conn.execute(
                sa.text(
                    'INSERT INTO pipeline_stage_configs (stage_name, "order", weight) '
                    'VALUES (:stage_name, :order, :weight)'
                ),
                {
                    'stage_name': stage_name,
                    'order': order,
                    'weight': weight,
                },
            )


def downgrade():
    conn = op.get_bind()
    for stage_name, _order, _weight in _STAGES:
        conn.execute(
            sa.text('DELETE FROM pipeline_stage_configs WHERE stage_name = :n'),
            {'n': stage_name},
        )
    for stage_name, order, weight in _LEGACY_DOWNGRADE:
        conn.execute(
            sa.text(
                'INSERT INTO pipeline_stage_configs (stage_name, "order", weight) '
                'VALUES (:stage_name, :order, :weight)'
            ),
            {'stage_name': stage_name, 'order': order, 'weight': weight},
        )
