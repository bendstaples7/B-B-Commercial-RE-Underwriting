"""Add explicit recommended-action hold state.

Revision ID: rs_hold_20260715
Revises: u0v1w2x3y4z5
"""

from alembic import op


revision = 'rs_hold_20260715'
down_revision = 'u0v1w2x3y4z5'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TYPE crm_recommended_action_enum "
        "ADD VALUE IF NOT EXISTS 'hold'"
    )


def downgrade():
    # PostgreSQL cannot remove an enum value safely without rebuilding every
    # dependent column. Clear persisted values so the previous application
    # model can deserialize every row, then retain the unused enum label.
    op.execute(
        "UPDATE leads SET recommended_action = NULL "
        "WHERE recommended_action = 'hold'"
    )
