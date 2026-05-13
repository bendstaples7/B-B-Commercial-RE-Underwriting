"""commercial om intake schema

Revision ID: d4e5f6g7h8i9
Revises: c3d4e5f6g7h8
Create Date: 2026-05-10 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'd4e5f6g7h8i9'
down_revision = 'c3d4e5f6g7h8'
branch_labels = None
depends_on = None


def upgrade():
    # 1. om_intake_jobs (FK -> deals.id, nullable)
    op.create_table(
        'om_intake_jobs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.String(length=255), nullable=False),
        sa.Column('original_filename', sa.String(length=500), nullable=False),
        sa.Column('intake_status', sa.String(length=20), nullable=False),

        # PDF storage and extraction results
        sa.Column('pdf_bytes', sa.LargeBinary(), nullable=True),
        sa.Column('raw_text', sa.Text(), nullable=True),
        sa.Column('tables_json', sa.JSON(), nullable=True),
        sa.Column('table_extraction_warning', sa.Text(), nullable=True),

        # AI extraction and analysis results
        sa.Column('extracted_om_data', sa.JSON(), nullable=True),
        sa.Column('scenario_comparison', sa.JSON(), nullable=True),
        sa.Column('market_rent_results', sa.JSON(), nullable=True),
        sa.Column('consistency_warnings', sa.JSON(), nullable=True),
        sa.Column('market_research_warnings', sa.JSON(), nullable=True),

        # Validation flags
        sa.Column('partial_realistic_scenario_warning', sa.Boolean(), nullable=True),
        sa.Column('asking_price_missing_error', sa.Boolean(), nullable=True),
        sa.Column('unit_count_missing_error', sa.Boolean(), nullable=True),

        # Failure tracking
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('failed_at_stage', sa.String(length=20), nullable=True),

        # Link to created Deal on confirmation
        sa.Column('deal_id', sa.Integer(), nullable=True),

        # Timestamps
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('expires_at', sa.DateTime(), nullable=False),

        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['deal_id'], ['deals.id'], name='fk_om_intake_jobs_deal_id'),
        sa.CheckConstraint(
            "intake_status IN ('PENDING','PARSING','EXTRACTING','RESEARCHING','REVIEW','CONFIRMED','FAILED')",
            name='ck_om_intake_jobs_status',
        ),
    )
    op.create_index('ix_om_intake_jobs_user_id', 'om_intake_jobs', ['user_id'])
    op.create_index('ix_om_intake_jobs_user_created', 'om_intake_jobs', ['user_id', 'created_at'])

    # 2. om_field_overrides (FK -> om_intake_jobs.id with CASCADE)
    op.create_table(
        'om_field_overrides',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('om_intake_job_id', sa.Integer(), nullable=False),
        sa.Column('field_name', sa.String(length=100), nullable=False),
        sa.Column('original_value', sa.JSON(), nullable=True),
        sa.Column('overridden_value', sa.JSON(), nullable=True),
        sa.Column('overridden_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),

        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(
            ['om_intake_job_id'],
            ['om_intake_jobs.id'],
            name='fk_om_field_overrides_om_intake_job_id',
            ondelete='CASCADE',
        ),
        sa.UniqueConstraint(
            'om_intake_job_id', 'field_name',
            name='uq_om_field_override_job_field',
        ),
    )


def downgrade():
    # Drop tables in reverse dependency order
    op.drop_table('om_field_overrides')
    op.drop_table('om_intake_jobs')
