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
    # Drop goals whose user_id no longer exists so ADD CONSTRAINT can validate.
    op.execute(
        """
        DELETE FROM user_activity_goals AS g
        WHERE NOT EXISTS (
            SELECT 1 FROM users AS u WHERE u.user_id = g.user_id
        )
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint AS c
                JOIN pg_class AS t ON c.conrelid = t.oid
                JOIN pg_namespace AS n ON t.relnamespace = n.oid
                WHERE c.conname = 'fk_user_activity_goals_user_id'
                  AND t.relname = 'user_activity_goals'
                  AND n.nspname = current_schema()
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
