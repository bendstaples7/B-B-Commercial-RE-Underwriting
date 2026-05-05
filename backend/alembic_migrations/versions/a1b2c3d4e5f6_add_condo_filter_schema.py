"""add condo filter schema

Revision ID: a1b2c3d4e5f6
Revises: 267725fe7017
Create Date: 2026-05-04 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '267725fe7017'
branch_labels = None
depends_on = None


def upgrade():
    # Create address_group_analyses table
    op.create_table(
        'address_group_analyses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('normalized_address', sa.String(length=500), nullable=False),
        sa.Column('source_type', sa.String(length=50), nullable=True),
        sa.Column('property_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('pin_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('owner_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('has_unit_number', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('has_condo_language', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('missing_pin_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('missing_owner_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('condo_risk_status', sa.String(length=50), nullable=False),
        sa.Column('building_sale_possible', sa.String(length=50), nullable=False),
        sa.Column('analysis_details', sa.JSON(), nullable=True),
        sa.Column('manually_reviewed', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('manual_override_status', sa.String(length=50), nullable=True),
        sa.Column('manual_override_reason', sa.Text(), nullable=True),
        sa.Column('analyzed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
    )

    # Create indexes on address_group_analyses
    op.create_index(
        'ix_address_group_analyses_normalized_address',
        'address_group_analyses',
        ['normalized_address'],
        unique=True,
    )
    op.create_index(
        'ix_address_group_analyses_condo_risk_status',
        'address_group_analyses',
        ['condo_risk_status'],
        unique=False,
    )

    # Add condo filter columns to leads table
    with op.batch_alter_table('leads', schema=None) as batch_op:
        batch_op.add_column(sa.Column('condo_risk_status', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('building_sale_possible', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('condo_analysis_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_leads_condo_analysis_id',
            'address_group_analyses',
            ['condo_analysis_id'],
            ['id'],
        )


def downgrade():
    # Remove condo filter columns from leads table
    with op.batch_alter_table('leads', schema=None) as batch_op:
        batch_op.drop_constraint('fk_leads_condo_analysis_id', type_='foreignkey')
        batch_op.drop_column('condo_analysis_id')
        batch_op.drop_column('building_sale_possible')
        batch_op.drop_column('condo_risk_status')

    # Drop indexes and table
    op.drop_index('ix_address_group_analyses_condo_risk_status', table_name='address_group_analyses')
    op.drop_index('ix_address_group_analyses_normalized_address', table_name='address_group_analyses')
    op.drop_table('address_group_analyses')
