"""Add FK from user_activity_goals.user_id to users.user_id.

Revision ID: act_goals_fk_20260716
Revises: act_tl_idx_20260715
"""

from alembic import op


revision = 'act_goals_fk_20260716'
down_revision = 'act_tl_idx_20260715'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'fk_user_activity_goals_user_id'
            ) THEN
                ALTER TABLE user_activity_goals
                ADD CONSTRAINT fk_user_activity_goals_user_id
                FOREIGN KEY (user_id)
                REFERENCES users (user_id)
                ON DELETE CASCADE;
            END IF;
        END
        $$;
        """
    )


def downgrade():
    op.execute(
        """
        ALTER TABLE user_activity_goals
        DROP CONSTRAINT IF EXISTS fk_user_activity_goals_user_id
        """
    )
