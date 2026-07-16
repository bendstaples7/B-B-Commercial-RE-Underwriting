"""Add user_activity_goals for CRM activity dashboard.

Revision ID: act_goals_20260715
Revises: rs_task_key_20260715
"""

from alembic import op


revision = 'act_goals_20260715'
down_revision = 'rs_task_key_20260715'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_activity_goals (
            id SERIAL PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL,
            period_type VARCHAR(20) NOT NULL,
            metric VARCHAR(20) NOT NULL,
            target INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
            CONSTRAINT ck_user_activity_goals_period_type
                CHECK (period_type IN ('weekly', 'monthly')),
            CONSTRAINT ck_user_activity_goals_metric
                CHECK (metric IN ('calls', 'mailers', 'emails', 'notes', 'tasks')),
            CONSTRAINT ck_user_activity_goals_target_nonneg
                CHECK (target >= 0),
            CONSTRAINT uq_user_activity_goals_user_period_metric
                UNIQUE (user_id, period_type, metric)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_user_activity_goals_user_id
        ON user_activity_goals (user_id)
        """
    )


def downgrade():
    op.execute("DROP INDEX IF EXISTS ix_user_activity_goals_user_id")
    op.execute("DROP TABLE IF EXISTS user_activity_goals")
