"""Add violation_data, permit_data columns to leads and data_enrichment_weight to scoring_weights

Revision ID: 97321ab5e710
Revises: h2i3j4k5l6m7
Create Date: 2026-06-26 11:53:41.549700

Adds three new columns required for the Data Enrichment Scoring feature:
- leads.violation_data (JSONB, nullable) — stores code violation records
- leads.permit_data (JSONB, nullable) — stores building permit records
- scoring_weights.data_enrichment_weight (FLOAT, NOT NULL, default 0.20)
  — configurable weight for data enrichment in lead scoring

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '97321ab5e710'
down_revision = 'h2i3j4k5l6m7'
branch_labels = None
depends_on = None


def upgrade():
    # Add violation_data (JSONB, nullable) to leads
    op.add_column(
        'leads',
        sa.Column('violation_data', postgresql.JSONB(), nullable=True),
    )
    # Add permit_data (JSONB, nullable) to leads
    op.add_column(
        'leads',
        sa.Column('permit_data', postgresql.JSONB(), nullable=True),
    )
    # Add data_enrichment_weight (FLOAT, NOT NULL, default 0.20) to scoring_weights
    op.add_column(
        'scoring_weights',
        sa.Column(
            'data_enrichment_weight',
            sa.Float(),
            nullable=False,
            server_default='0.20',
        ),
    )


def downgrade():
    op.drop_column('scoring_weights', 'data_enrichment_weight')
    op.drop_column('leads', 'permit_data')
    op.drop_column('leads', 'violation_data')