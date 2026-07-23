"""Unify awaiting_skip_trace into a single skip_trace stage.

Revision ID: unif_st_20260723
Revises: skp_trc_20260723

- Clear dated non-hold chores on awaiting leads (avoid Today's Action flood)
- Convert matured recent_sale_hold rows into undated handoffs
- Ensure an undated skip_trace_owner handoff where missing (non mid-hold)
- Flip lead_status awaiting → skip_trace; needs=false only while mid-hold
- Drop awaiting from pipeline_stage_configs; renumber skip_trace to order 0
- Leave Postgres enum label awaiting_skip_trace unused (drop deferred)
"""
from alembic import op
import sqlalchemy as sa


revision = 'unif_st_20260723'
down_revision = 'skp_trc_20260723'
branch_labels = None
depends_on = None

_STAGES = (
    ('skip_trace', 0, -5.0),
    ('mailing_no_contact_made', 1, 0.0),
    ('mailing_contacted_no_interest', 2, -15.0),
    ('mailing_contacted_interested', 3, 20.0),
    ('negotiating_remote', 4, 35.0),
    ('in_person_appointment', 5, 45.0),
    ('offer_delivered', 6, 55.0),
    ('deprioritize', 7, -25.0),
    ('deal_won', 8, 0.0),
    ('deal_lost', 9, -30.0),
    ('suppressed', 10, -40.0),
    ('do_not_contact', 11, -40.0),
)


def upgrade():
    conn = op.get_bind()

    # 1) Complete dated leak chores on awaiting leads (not recent_sale_hold).
    conn.execute(sa.text("""
        UPDATE lead_tasks AS t
        SET status = 'completed',
            completed_at = COALESCE(completed_at, NOW())
        FROM leads AS l
        WHERE t.lead_id = l.id
          AND l.lead_status = 'awaiting_skip_trace'
          AND t.status = 'open'
          AND t.due_date IS NOT NULL
          AND (t.workflow_key IS NULL OR t.workflow_key <> 'recent_sale_hold')
    """))

    # 2) Matured holds (due <= today) → undated handoff so Today's Action
    #    does not flood until the hourly activator runs.
    conn.execute(sa.text("""
        UPDATE lead_tasks AS t
        SET title = 'Awaiting skip trace',
            workflow_key = 'awaiting_skip_trace_handoff',
            due_date = NULL
        FROM leads AS l
        WHERE t.lead_id = l.id
          AND l.lead_status = 'awaiting_skip_trace'
          AND t.status = 'open'
          AND t.task_type = 'skip_trace_owner'
          AND t.workflow_key = 'recent_sale_hold'
          AND t.due_date IS NOT NULL
          AND t.due_date <= CURRENT_DATE
    """))

    # 3) Normalize existing undated skip_trace_owner open tasks into handoff shape.
    conn.execute(sa.text("""
        UPDATE lead_tasks AS t
        SET title = 'Awaiting skip trace',
            workflow_key = 'awaiting_skip_trace_handoff',
            due_date = NULL
        FROM leads AS l
        WHERE t.lead_id = l.id
          AND l.lead_status = 'awaiting_skip_trace'
          AND t.status = 'open'
          AND t.task_type = 'skip_trace_owner'
          AND t.due_date IS NULL
    """))

    # 4) Insert undated handoff where awaiting lead has no open skip_trace_owner
    #    (mid-hold rows already have a future recent_sale_hold owner task).
    conn.execute(sa.text("""
        INSERT INTO lead_tasks (
            lead_id, task_type, title, status, due_date, workflow_key, created_by, created_at
        )
        SELECT
            l.id,
            CAST('skip_trace_owner' AS lead_task_type_enum),
            'Awaiting skip trace',
            CAST('open' AS lead_task_status_enum),
            NULL,
            'awaiting_skip_trace_handoff',
            'unif_st_20260723',
            NOW()
        FROM leads AS l
        WHERE l.lead_status = 'awaiting_skip_trace'
          AND NOT EXISTS (
              SELECT 1 FROM lead_tasks AS t
              WHERE t.lead_id = l.id
                AND t.status = 'open'
                AND t.task_type = 'skip_trace_owner'
          )
    """))

    # 5) Flip status. Mid-hold keeps needs=false; everyone else needs active work.
    conn.execute(sa.text("""
        UPDATE leads AS l
        SET lead_status = 'skip_trace',
            needs_skip_trace = EXISTS (
                SELECT 1 FROM lead_tasks AS t
                WHERE t.lead_id = l.id
                  AND t.status = 'open'
                  AND t.task_type = 'skip_trace_owner'
                  AND t.workflow_key = 'recent_sale_hold'
                  AND t.due_date IS NOT NULL
                  AND t.due_date > CURRENT_DATE
            ) IS FALSE
        WHERE l.lead_status = 'awaiting_skip_trace'
    """))

    # 6) Pipeline configs: remove awaiting; rewrite remaining stage rows.
    conn.execute(sa.text(
        "DELETE FROM pipeline_stage_configs WHERE stage_name = 'awaiting_skip_trace'"
    ))

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
    # Enum value remains; reverse status flip only for rows that still look like
    # undated handoff-only skip_trace with needs=true (best-effort, not perfect).
    conn = op.get_bind()
    conn.execute(sa.text("""
        UPDATE leads
        SET lead_status = 'awaiting_skip_trace'
        WHERE lead_status = 'skip_trace'
          AND needs_skip_trace IS TRUE
          AND EXISTS (
              SELECT 1 FROM lead_tasks t
              WHERE t.lead_id = leads.id
                AND t.status = 'open'
                AND t.workflow_key = 'awaiting_skip_trace_handoff'
                AND t.due_date IS NULL
          )
          AND NOT EXISTS (
              SELECT 1 FROM lead_tasks t
              WHERE t.lead_id = leads.id
                AND t.status = 'open'
                AND t.workflow_key = 'recent_sale_hold'
          )
    """))
    conn.execute(sa.text("""
        INSERT INTO pipeline_stage_configs (stage_name, "order", weight)
        SELECT 'awaiting_skip_trace', 0, -10.0
        WHERE NOT EXISTS (
            SELECT 1 FROM pipeline_stage_configs WHERE stage_name = 'awaiting_skip_trace'
        )
    """))
