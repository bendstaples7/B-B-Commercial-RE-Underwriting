"""Widen il_sos_llc_managers.mm_file_date for ISO CSV dates.

Revision ID: n3o4p5q6r7s8
Revises: m2n3o4p5q6r7
Create Date: 2026-07-12
"""
from alembic import op
import sqlalchemy as sa

revision = 'n3o4p5q6r7s8'
down_revision = 'm2n3o4p5q6r7'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('il_sos_llc_managers') as batch_op:
        batch_op.alter_column(
            'mm_file_date',
            existing_type=sa.String(8),
            type_=sa.String(20),
            existing_nullable=True,
        )


def downgrade():
    with op.batch_alter_table('il_sos_llc_managers') as batch_op:
        batch_op.alter_column(
            'mm_file_date',
            existing_type=sa.String(20),
            type_=sa.String(8),
            existing_nullable=True,
        )
