"""Upsert lead_status pipeline stage weights (preserve unknown custom? delete legacy only).

Revision ID: lead_stg_20260722
Revises: rtm_idx_20260721
"""

from alembic import op
import sqlalchemy as sa

from app.services.lead_pipeline_stages import LEAD_PIPELINE_STAGES


revision = 'lead_stg_20260722'
down_revision = 'rtm_idx_20260721'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    known = {s['stage_name'] for s in LEAD_PIPELINE_STAGES}
    # Remove only legacy / unknown labels (Draft, Lead, etc.) — do not wipe
    # the whole table so customized weights for known stages are upserted.
    existing = conn.execute(
        sa.text('SELECT stage_name FROM pipeline_stage_configs')
    ).fetchall()
    for (stage_name,) in existing:
        if stage_name not in known:
            conn.execute(
                sa.text('DELETE FROM pipeline_stage_configs WHERE stage_name = :n'),
                {'n': stage_name},
            )

    for stage in LEAD_PIPELINE_STAGES:
        row = conn.execute(
            sa.text(
                'SELECT id FROM pipeline_stage_configs WHERE stage_name = :n'
            ),
            {'n': stage['stage_name']},
        ).fetchone()
        if row:
            conn.execute(
                sa.text(
                    'UPDATE pipeline_stage_configs '
                    'SET "order" = :order, weight = :weight '
                    'WHERE stage_name = :stage_name'
                ),
                {
                    'stage_name': stage['stage_name'],
                    'order': stage['order'],
                    'weight': stage['weight'],
                },
            )
        else:
            conn.execute(
                sa.text(
                    'INSERT INTO pipeline_stage_configs (stage_name, "order", weight) '
                    'VALUES (:stage_name, :order, :weight)'
                ),
                {
                    'stage_name': stage['stage_name'],
                    'order': stage['order'],
                    'weight': stage['weight'],
                },
            )


def downgrade():
    conn = op.get_bind()
    known = {s['stage_name'] for s in LEAD_PIPELINE_STAGES}
    for stage_name in known:
        conn.execute(
            sa.text('DELETE FROM pipeline_stage_configs WHERE stage_name = :n'),
            {'n': stage_name},
        )
    legacy = (
        ('Draft', 0, 0.5),
        ('Lead', 1, 1.0),
        ('Qualification', 2, 3.0),
        ('Proposal', 3, 5.0),
        ('Negotiation', 4, 8.0),
        ('Closed Won', 5, 10.0),
        ('Closed Lost', 6, 0.0),
    )
    for stage_name, order, weight in legacy:
        conn.execute(
            sa.text(
                'INSERT INTO pipeline_stage_configs (stage_name, "order", weight) '
                'VALUES (:stage_name, :order, :weight)'
            ),
            {'stage_name': stage_name, 'order': order, 'weight': weight},
        )
