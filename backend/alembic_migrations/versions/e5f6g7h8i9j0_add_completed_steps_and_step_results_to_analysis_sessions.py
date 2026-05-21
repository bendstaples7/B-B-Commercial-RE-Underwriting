"""add completed_steps and step_results to analysis_sessions

Revision ID: e5f6g7h8i9j0
Revises: d4e5f6g7h8i9
Create Date: 2026-05-07 12:00:00.000000

Adds two JSON audit-trail columns to ``analysis_sessions``:

- ``completed_steps``: JSON array of step name strings recording which
  workflow steps have been fully executed, e.g.
  ``["PROPERTY_FACTS", "COMPARABLE_SEARCH"]``.  Defaults to ``[]``.

- ``step_results``: JSON object storing the result dict from each
  ``_execute_step`` call, keyed by step name, e.g.
  ``{"COMPARABLE_SEARCH": {"comparable_count": 8, "status": "complete"}}``.
  Defaults to ``{}``.

Both columns are nullable=False with server defaults so existing rows
are unaffected.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'e5f6g7h8i9j0'
down_revision = 'd4e5f6g7h8i9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'analysis_sessions',
        sa.Column(
            'completed_steps',
            sa.JSON(),
            nullable=False,
            server_default='[]',
        ),
    )
    op.add_column(
        'analysis_sessions',
        sa.Column(
            'step_results',
            sa.JSON(),
            nullable=False,
            server_default='{}',
        ),
    )


def downgrade():
    op.drop_column('analysis_sessions', 'step_results')
    op.drop_column('analysis_sessions', 'completed_steps')
