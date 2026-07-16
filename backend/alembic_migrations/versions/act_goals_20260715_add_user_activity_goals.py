"""Add user_activity_goals for CRM activity dashboard.

Revision ID: act_goals_20260715
Revises: rs_task_key_20260715
"""

from alembic import op
import sqlalchemy as sa


revision = 'act_goals_20260715'
down_revision = 'rs_task_key_20260715'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'user_activity_goals',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('period_type', sa.String(length=20), nullable=False),
        sa.Column('metric', sa.String(length=20), nullable=False),
        sa.Column('target', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.CheckConstraint(
            "period_type IN ('weekly', 'monthly')",
            name='ck_user_activity_goals_period_type',
        ),
        sa.CheckConstraint(
            "metric IN ('calls', 'mailers', 'emails', 'notes', 'tasks')",
            name='ck_user_activity_goals_metric',
        ),
        sa.CheckConstraint(
            'target >= 0',
            name='ck_user_activity_goals_target_nonneg',
        ),
        sa.UniqueConstraint(
            'user_id', 'period_type', 'metric',
            name='uq_user_activity_goals_user_period_metric',
        ),
    )
    op.create_index(
        'ix_user_activity_goals_user_id',
        'user_activity_goals',
        ['user_id'],
    )


def downgrade():
    op.drop_index('ix_user_activity_goals_user_id', table_name='user_activity_goals')
    op.drop_table('user_activity_goals')
