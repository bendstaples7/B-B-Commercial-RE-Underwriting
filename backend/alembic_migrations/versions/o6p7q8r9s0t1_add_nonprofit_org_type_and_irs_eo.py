"""Add nonprofit org_type and IRS EO BMF lookup table.

Revision ID: o6p7q8r9s0t1
Revises: n3o4p5q6r7s8
Create Date: 2026-07-12

Supports entity/nonprofit mail deprioritization: classify organizations as
nonprofit and look up IRS Exempt Organizations Business Master File rows.
"""
from alembic import op
import sqlalchemy as sa


revision = 'o6p7q8r9s0t1'
down_revision = 'n3o4p5q6r7s8'
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TYPE org_type_enum ADD VALUE IF NOT EXISTS 'nonprofit'"
    )

    op.create_table(
        'irs_eo_organizations',
        sa.Column('ein', sa.String(9), primary_key=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('normalized_name', sa.String(200), nullable=False),
        sa.Column('city', sa.String(64), nullable=True),
        sa.Column('state', sa.String(2), nullable=True),
        sa.Column('ntee_cd', sa.String(10), nullable=True),
        sa.Column('subsection', sa.String(4), nullable=True),
        sa.Column('status', sa.String(2), nullable=True),
        sa.Column(
            'imported_at',
            sa.DateTime(),
            nullable=False,
            server_default=sa.text('CURRENT_TIMESTAMP'),
        ),
    )
    op.create_index(
        'ix_irs_eo_organizations_normalized_name',
        'irs_eo_organizations',
        ['normalized_name'],
    )
    op.create_index(
        'ix_irs_eo_organizations_state_normalized_name',
        'irs_eo_organizations',
        ['state', 'normalized_name'],
    )


def downgrade():
    op.drop_index(
        'ix_irs_eo_organizations_state_normalized_name',
        table_name='irs_eo_organizations',
    )
    op.drop_index(
        'ix_irs_eo_organizations_normalized_name',
        table_name='irs_eo_organizations',
    )
    op.drop_table('irs_eo_organizations')
    # PostgreSQL cannot easily remove enum values; leave nonprofit in place.
