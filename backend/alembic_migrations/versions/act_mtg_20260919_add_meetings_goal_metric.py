"""Allow meetings as a CRM activity-dashboard goal metric.

Revision ID: act_mtg_20260919
Revises: mtg_log_20260918
Create Date: 2026-09-19
"""
from alembic import op

revision = 'act_mtg_20260919'
down_revision = 'mtg_log_20260918'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return
    op.execute("ALTER TABLE user_activity_goals DROP CONSTRAINT IF EXISTS ck_user_activity_goals_metric")
    op.execute(
        """
        ALTER TABLE user_activity_goals
        ADD CONSTRAINT ck_user_activity_goals_metric
        CHECK (metric IN ('calls', 'meetings', 'mailers', 'emails', 'notes', 'tasks'))
        """
    )


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return
    op.execute("ALTER TABLE user_activity_goals DROP CONSTRAINT IF EXISTS ck_user_activity_goals_metric")
    op.execute(
        """
        ALTER TABLE user_activity_goals
        ADD CONSTRAINT ck_user_activity_goals_metric
        CHECK (metric IN ('calls', 'mailers', 'emails', 'notes', 'tasks'))
        """
    )
