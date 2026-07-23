"""Heal mid-hold needs flag and matured recent_sale_hold rows.

Revision ID: heal_st_20260723
Revises: unif_st_20260723

For databases that already applied the first unify revision (which set
needs_skip_trace=TRUE for every awaiting→skip_trace flip):

- Mid-hold (open future recent_sale_hold): needs_skip_trace=FALSE
- Matured holds (due <= today): convert to undated handoff + needs=TRUE
- Active skip_trace with needs=TRUE and no open skip_trace_owner: insert handoff
"""
from alembic import op
import sqlalchemy as sa


revision = 'heal_st_20260723'
down_revision = 'unif_st_20260723'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    # 1) Matured holds → undated handoff (avoid Today's Action flood).
    conn.execute(sa.text("""
        UPDATE lead_tasks AS t
        SET title = 'Awaiting skip trace',
            workflow_key = 'awaiting_skip_trace_handoff',
            due_date = NULL
        FROM leads AS l
        WHERE t.lead_id = l.id
          AND l.lead_status = 'skip_trace'
          AND t.status = 'open'
          AND t.task_type = 'skip_trace_owner'
          AND t.workflow_key = 'recent_sale_hold'
          AND t.due_date IS NOT NULL
          AND t.due_date <= CURRENT_DATE
    """))

    # 2) Mid-hold: force needs=false while a future recent_sale_hold is open.
    conn.execute(sa.text("""
        UPDATE leads AS l
        SET needs_skip_trace = FALSE
        WHERE l.lead_status = 'skip_trace'
          AND EXISTS (
              SELECT 1 FROM lead_tasks AS t
              WHERE t.lead_id = l.id
                AND t.status = 'open'
                AND t.task_type = 'skip_trace_owner'
                AND t.workflow_key = 'recent_sale_hold'
                AND t.due_date IS NOT NULL
                AND t.due_date > CURRENT_DATE
          )
    """))

    # 3) Non mid-hold skip_trace rows should need active work.
    conn.execute(sa.text("""
        UPDATE leads AS l
        SET needs_skip_trace = TRUE
        WHERE l.lead_status = 'skip_trace'
          AND NOT EXISTS (
              SELECT 1 FROM lead_tasks AS t
              WHERE t.lead_id = l.id
                AND t.status = 'open'
                AND t.task_type = 'skip_trace_owner'
                AND t.workflow_key = 'recent_sale_hold'
                AND t.due_date IS NOT NULL
                AND t.due_date > CURRENT_DATE
          )
          AND (l.needs_skip_trace IS DISTINCT FROM TRUE)
    """))

    # 4) Ensure undated handoff where active skip work has no owner task.
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
            'heal_st_20260723',
            NOW()
        FROM leads AS l
        WHERE l.lead_status = 'skip_trace'
          AND l.needs_skip_trace IS TRUE
          AND NOT EXISTS (
              SELECT 1 FROM lead_tasks AS t
              WHERE t.lead_id = l.id
                AND t.status = 'open'
                AND t.task_type = 'skip_trace_owner'
          )
    """))


def downgrade():
    # Best-effort: remove handoffs created only by this heal revision.
    conn = op.get_bind()
    conn.execute(sa.text("""
        DELETE FROM lead_tasks
        WHERE created_by = 'heal_st_20260723'
          AND workflow_key = 'awaiting_skip_trace_handoff'
          AND status = 'open'
          AND due_date IS NULL
    """))
