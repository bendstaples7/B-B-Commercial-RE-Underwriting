"""add lead_scores table

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-05 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6g7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'lead_scores',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('lead_id', sa.Integer(), sa.ForeignKey('leads.id'), nullable=False),
        sa.Column('property_id', sa.Integer(), nullable=True),
        sa.Column('score_version', sa.String(length=50), nullable=False),
        sa.Column('total_score', sa.Float(), nullable=False),
        sa.Column('score_tier', sa.String(length=1), nullable=False),
        sa.Column('data_quality_score', sa.Float(), nullable=False),
        sa.Column('recommended_action', sa.String(length=50), nullable=False),
        sa.Column('top_signals', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('score_details', postgresql.JSONB(), nullable=False, server_default='{}'),
        sa.Column('missing_data', postgresql.JSONB(), nullable=False, server_default='[]'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_lead_scores_lead_id', 'lead_scores', ['lead_id'])
    op.create_index('ix_lead_scores_created_at', 'lead_scores', ['created_at'])
    op.create_index('ix_lead_scores_score_tier', 'lead_scores', ['score_tier'])


def downgrade():
    op.drop_index('ix_lead_scores_score_tier', table_name='lead_scores')
    op.drop_index('ix_lead_scores_created_at', table_name='lead_scores')
    op.drop_index('ix_lead_scores_lead_id', table_name='lead_scores')
    op.drop_table('lead_scores')
