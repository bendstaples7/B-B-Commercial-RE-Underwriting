"""Illinois SOS LLC bulk entity / manager / agent tables.

Revision ID: m2n3o4p5q6r7
Revises: l1m2n3o4p5q6
Create Date: 2026-07-12

Free Business Data Transparency Act dumps (llcallnam/mgr/agt/mst) loaded
locally for Illinois LLC entity resolution.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'm2n3o4p5q6r7'
down_revision = 'l1m2n3o4p5q6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'il_sos_llc_entities',
        sa.Column('file_number', sa.String(8), primary_key=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('normalized_name', sa.String(200), nullable=False),
        sa.Column('status_code', sa.String(2), nullable=True),
        sa.Column('management_type', sa.String(1), nullable=True),
        sa.Column('juris_organized', sa.String(2), nullable=True),
        sa.Column('imported_at', sa.DateTime(), nullable=False),
    )
    op.create_index(
        'ix_il_sos_llc_entities_normalized_name',
        'il_sos_llc_entities',
        ['normalized_name'],
    )

    op.create_table(
        'il_sos_llc_managers',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('file_number', sa.String(8), nullable=False),
        sa.Column('mm_name', sa.String(120), nullable=False),
        sa.Column('mm_street', sa.String(60), nullable=True),
        sa.Column('mm_city', sa.String(40), nullable=True),
        sa.Column('mm_juris', sa.String(2), nullable=True),
        sa.Column('mm_zip', sa.String(10), nullable=True),
        sa.Column('mm_file_date', sa.String(8), nullable=True),
        sa.Column('mm_type_code', sa.String(1), nullable=True),
        sa.Column('is_company', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(
            ['file_number'], ['il_sos_llc_entities.file_number'], ondelete='CASCADE',
        ),
    )
    op.create_index(
        'ix_il_sos_llc_managers_file_number',
        'il_sos_llc_managers',
        ['file_number'],
    )

    op.create_table(
        'il_sos_llc_agents',
        sa.Column('file_number', sa.String(8), primary_key=True),
        sa.Column('agent_name', sa.String(120), nullable=False),
        sa.Column('agent_street', sa.String(60), nullable=True),
        sa.Column('agent_city', sa.String(40), nullable=True),
        sa.Column('agent_zip', sa.String(10), nullable=True),
        sa.Column('agent_code', sa.String(1), nullable=True),
        sa.ForeignKeyConstraint(
            ['file_number'], ['il_sos_llc_entities.file_number'], ondelete='CASCADE',
        ),
    )

    op.create_table(
        'il_sos_import_runs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('source', sa.String(100), nullable=False),
        sa.Column('status', sa.String(40), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('row_counts', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_table('il_sos_import_runs')
    op.drop_table('il_sos_llc_agents')
    op.drop_index('ix_il_sos_llc_managers_file_number', table_name='il_sos_llc_managers')
    op.drop_table('il_sos_llc_managers')
    op.drop_index('ix_il_sos_llc_entities_normalized_name', table_name='il_sos_llc_entities')
    op.drop_table('il_sos_llc_entities')
