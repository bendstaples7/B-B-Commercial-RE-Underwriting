"""add loading column to analysis_session

Revision ID: fd5451087f07
Revises: f6g7h8i9j0k1
Create Date: 2026-05-08 09:40:25.005545

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'fd5451087f07'
down_revision = 'f6g7h8i9j0k1'
branch_labels = None
depends_on = None


def upgrade():
    # Add loading column to analysis_sessions
    with op.batch_alter_table('analysis_sessions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('loading', sa.Boolean(), nullable=False, server_default=sa.false()))
        try:
            batch_op.drop_constraint('analysis_sessions_session_id_key', type_='unique')
        except Exception as e:
            if 'does not exist' not in str(e).lower():
                raise
        try:
            batch_op.drop_index('idx_analysis_sessions_session_id')
        except Exception as e:
            if 'does not exist' not in str(e).lower():
                raise
        try:
            batch_op.drop_index('idx_analysis_sessions_user_id')
        except Exception as e:
            if 'does not exist' not in str(e).lower():
                raise
        batch_op.create_index('ix_analysis_sessions_session_id', ['session_id'], unique=True)
        batch_op.create_index('ix_analysis_sessions_user_id', ['user_id'], unique=False)

    # Fix indexes on leads table
    with op.batch_alter_table('leads', schema=None) as batch_op:
        try:
            batch_op.drop_index('idx_leads_lead_category')
        except Exception as e:
            if 'does not exist' not in str(e).lower():
                raise
        try:
            batch_op.drop_index('ix_leads_condo_analysis_id')
        except Exception as e:
            if 'does not exist' not in str(e).lower():
                raise
        batch_op.create_index('ix_leads_lead_category', ['lead_category'], unique=False)

    # Fix indexes on comparable_sales
    with op.batch_alter_table('comparable_sales', schema=None) as batch_op:
        try:
            batch_op.drop_index('idx_comparable_sales_address')
        except Exception as e:
            if 'does not exist' not in str(e).lower():
                raise
        try:
            batch_op.drop_index('idx_comparable_sales_session_id')
        except Exception as e:
            if 'does not exist' not in str(e).lower():
                raise
        batch_op.create_index('ix_comparable_sales_address', ['address'], unique=False)
        batch_op.create_index('ix_comparable_sales_session_id', ['session_id'], unique=False)

    # Fix indexes on comparable_valuations
    with op.batch_alter_table('comparable_valuations', schema=None) as batch_op:
        try:
            batch_op.drop_index('idx_comparable_valuations_valuation_result_id')
        except Exception as e:
            if 'does not exist' not in str(e).lower():
                raise
        batch_op.create_index('ix_comparable_valuations_valuation_result_id', ['valuation_result_id'], unique=False)

    # Fix indexes on property_facts
    with op.batch_alter_table('property_facts', schema=None) as batch_op:
        try:
            batch_op.drop_index('idx_property_facts_address')
        except Exception as e:
            if 'does not exist' not in str(e).lower():
                raise
        try:
            batch_op.drop_index('idx_property_facts_session_id')
        except Exception as e:
            if 'does not exist' not in str(e).lower():
                raise
        batch_op.create_index('ix_property_facts_address', ['address'], unique=False)

    # Fix indexes on ranked_comparables
    with op.batch_alter_table('ranked_comparables', schema=None) as batch_op:
        try:
            batch_op.drop_index('idx_ranked_comparables_session_id')
        except Exception as e:
            if 'does not exist' not in str(e).lower():
                raise
        batch_op.create_index('ix_ranked_comparables_session_id', ['session_id'], unique=False)

    # Fix indexes on scenarios
    with op.batch_alter_table('scenarios', schema=None) as batch_op:
        try:
            batch_op.drop_index('idx_scenarios_session_id')
        except Exception as e:
            if 'does not exist' not in str(e).lower():
                raise
        batch_op.create_index('ix_scenarios_session_id', ['session_id'], unique=False)

    # Fix indexes on valuation_results
    with op.batch_alter_table('valuation_results', schema=None) as batch_op:
        try:
            batch_op.drop_index('idx_valuation_results_session_id')
        except Exception as e:
            if 'does not exist' not in str(e).lower():
                raise
        try:
            batch_op.drop_constraint('valuation_results_session_id_key', type_='unique')
        except Exception as e:
            if 'does not exist' not in str(e).lower():
                raise
        batch_op.create_index('ix_valuation_results_session_id', ['session_id'], unique=True)


def downgrade():
    with op.batch_alter_table('valuation_results', schema=None) as batch_op:
        batch_op.drop_index('ix_valuation_results_session_id')
        batch_op.create_unique_constraint('valuation_results_session_id_key', ['session_id'])
        batch_op.create_index('idx_valuation_results_session_id', ['session_id'], unique=False)

    with op.batch_alter_table('scenarios', schema=None) as batch_op:
        batch_op.drop_index('ix_scenarios_session_id')
        batch_op.create_index('idx_scenarios_session_id', ['session_id'], unique=False)

    with op.batch_alter_table('ranked_comparables', schema=None) as batch_op:
        batch_op.drop_index('ix_ranked_comparables_session_id')
        batch_op.create_index('idx_ranked_comparables_session_id', ['session_id'], unique=False)

    with op.batch_alter_table('property_facts', schema=None) as batch_op:
        batch_op.drop_index('ix_property_facts_address')
        batch_op.create_index('idx_property_facts_session_id', ['session_id'], unique=False)
        batch_op.create_index('idx_property_facts_address', ['address'], unique=False)

    with op.batch_alter_table('comparable_valuations', schema=None) as batch_op:
        batch_op.drop_index('ix_comparable_valuations_valuation_result_id')
        batch_op.create_index('idx_comparable_valuations_valuation_result_id', ['valuation_result_id'], unique=False)

    with op.batch_alter_table('comparable_sales', schema=None) as batch_op:
        batch_op.drop_index('ix_comparable_sales_session_id')
        batch_op.drop_index('ix_comparable_sales_address')
        batch_op.create_index('idx_comparable_sales_session_id', ['session_id'], unique=False)
        batch_op.create_index('idx_comparable_sales_address', ['address'], unique=False)

    with op.batch_alter_table('leads', schema=None) as batch_op:
        batch_op.drop_index('ix_leads_lead_category')
        batch_op.create_index('ix_leads_condo_analysis_id', ['condo_analysis_id'], unique=False)
        batch_op.create_index('idx_leads_lead_category', ['lead_category'], unique=False)

    with op.batch_alter_table('analysis_sessions', schema=None) as batch_op:
        batch_op.drop_index('ix_analysis_sessions_user_id')
        batch_op.drop_index('ix_analysis_sessions_session_id')
        batch_op.create_index('idx_analysis_sessions_user_id', ['user_id'], unique=False)
        batch_op.create_index('idx_analysis_sessions_session_id', ['session_id'], unique=False)
        batch_op.create_unique_constraint('analysis_sessions_session_id_key', ['session_id'])
        batch_op.drop_column('loading')
