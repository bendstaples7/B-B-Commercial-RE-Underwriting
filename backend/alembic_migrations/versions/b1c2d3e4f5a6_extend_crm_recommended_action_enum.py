"""Extend crm_recommended_action_enum with unified scoring action values.

Revision ID: b1c2d3e4f5a6
Revises: a4b5c6d7e8f9
Create Date: 2026-06-29

Adds scoring-derived recommended actions to the CRM enum so leads.recommended_action
and lead_scores.recommended_action share one vocabulary.
"""
from alembic import op

revision = 'b1c2d3e4f5a6'
down_revision = 'a4b5c6d7e8f9'
branch_labels = None
depends_on = None

_NEW_VALUES = (
    'review_now',
    'mail_ready',
    'call_ready',
    'valuation_needed',
    'needs_manual_review',
)


def upgrade():
    for value in _NEW_VALUES:
        op.execute(
            f"ALTER TYPE crm_recommended_action_enum ADD VALUE IF NOT EXISTS '{value}'"
        )


def downgrade():
    # PostgreSQL does not support removing enum values safely.
    pass
