"""Index lead_timeline_entries for activity dashboard actor+time queries.

Revision ID: act_tl_idx_20260715
Revises: act_goals_20260715
"""

from alembic import op


revision = 'act_tl_idx_20260715'
down_revision = 'act_goals_20260715'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_timeline_actor_occurred
        ON lead_timeline_entries (actor, occurred_at)
        """
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_timeline_actor_occurred")
